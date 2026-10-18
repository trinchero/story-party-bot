"""SQLite state machine. Network calls happen only after a durable claim."""
import json
import secrets
import sqlite3
import fcntl
from pathlib import Path
from contextlib import contextmanager


class RuleError(ValueError):
    pass


class Store:
    @classmethod
    def connect_existing(cls, path):
        """Connect without schema changes or crash recovery while the bot runs."""
        store = cls.__new__(cls)
        store.db = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=rw', uri=True, isolation_level=None)
        store.db.row_factory = sqlite3.Row
        store.db.execute('PRAGMA foreign_keys=ON')
        store.db.execute('CREATE TABLE IF NOT EXISTS withdrawn_players(player INTEGER PRIMARY KEY)')
        return store

    @contextmanager
    def operation(self):
        path = self.db.execute('PRAGMA database_list').fetchone()['file']
        with open(path + '.control.lock', 'a') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise RuleError('Hay una operación en curso. Espera y vuelve a intentarlo.') from None
            try:
                yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def close_game(self):
        g = self.game()
        if not g or g['status'] == 'finished':
            raise RuleError('La partida ya está cerrada.')
        for message in self.incomplete():
            self.skip(message['id'], 'Cierre manual confirmado desde la web')
        self.db.execute("UPDATE games SET status='finished' WHERE id=?", (g['id'],))
        self.bump('web_close')

    def __init__(self, path):
        self.db = sqlite3.connect(path, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
            PRAGMA journal_mode=WAL;
            PRAGMA synchronous=FULL;
            PRAGMA foreign_keys=ON;
            CREATE TABLE IF NOT EXISTS players(id INTEGER PRIMARY KEY, name TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS withdrawn_players(player INTEGER PRIMARY KEY);
            CREATE TABLE IF NOT EXISTS games(
                id INTEGER PRIMARY KEY, title TEXT NOT NULL, content TEXT NOT NULL,
                phase INTEGER NOT NULL DEFAULT 0, revision INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'preparing', cards INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value INTEGER);
            CREATE TABLE IF NOT EXISTS assignments(
                game INTEGER REFERENCES games(id), code TEXT, player INTEGER REFERENCES players(id),
                PRIMARY KEY(game,code), UNIQUE(game,player));
            CREATE TABLE IF NOT EXISTS messages(
                id INTEGER PRIMARY KEY, game INTEGER REFERENCES games(id), phase INTEGER,
                position INTEGER, title TEXT, body TEXT, recipients TEXT,
                status TEXT NOT NULL DEFAULT 'pending', UNIQUE(game,phase,position));
            CREATE TABLE IF NOT EXISTS deliveries(
                id INTEGER PRIMARY KEY, message INTEGER REFERENCES messages(id), code TEXT,
                player INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
                error TEXT, telegram_id INTEGER, UNIQUE(message,player));
            CREATE TABLE IF NOT EXISTS buttons(
                token TEXT PRIMARY KEY, game INTEGER, revision INTEGER, action TEXT,
                payload TEXT, used INTEGER DEFAULT 0);
            CREATE TABLE IF NOT EXISTS drafts(id TEXT PRIMARY KEY, title TEXT, content TEXT);
            CREATE TABLE IF NOT EXISTS audit(
                id INTEGER PRIMARY KEY, game INTEGER, action TEXT, detail TEXT,
                created TEXT DEFAULT CURRENT_TIMESTAMP);
        ''')
        # The process lock must be held before opening the production database.
        self.db.execute("UPDATE deliveries SET status='uncertain',error='Interrupción durante el envío' WHERE status='sending'")

    @contextmanager
    def transaction(self):
        self.db.execute('BEGIN IMMEDIATE')
        try:
            yield
            self.db.execute('COMMIT')
        except BaseException:
            self.db.execute('ROLLBACK')
            raise

    def rows(self, sql, args=()):
        return self.db.execute(sql, args).fetchall()

    def game(self):
        row = self.db.execute("SELECT g.* FROM games g JOIN settings s ON s.value=g.id WHERE s.key='current'").fetchone()
        return dict(row) if row else None

    def content(self):
        return json.loads(self.game()['content'])

    def bump(self, action, detail=''):
        gid = self.game()['id']
        self.db.execute('UPDATE games SET revision=revision+1 WHERE id=?', (gid,))
        self.db.execute('INSERT INTO audit(game,action,detail) VALUES(?,?,?)', (gid, action, str(detail)))

    def draft(self, title, content):
        token = secrets.token_hex(8)
        self.db.execute('INSERT INTO drafts VALUES(?,?,?)', (token, title, json.dumps(content)))
        return token

    def new_game(self, draft):
        old = self.game()
        if old and old['status'] != 'finished':
            raise RuleError('Finaliza la partida actual antes de crear otra.')
        row = self.db.execute('SELECT * FROM drafts WHERE id=?', (draft,)).fetchone()
        if not row:
            raise RuleError('Carga el Numbers de nuevo.')
        cur = self.db.execute('INSERT INTO games(title,content) VALUES(?,?)', (row['title'], row['content']))
        self.db.execute("INSERT OR REPLACE INTO settings VALUES('current',?)", (cur.lastrowid,))
        self.db.execute('DELETE FROM drafts WHERE id=?', (draft,))
        self.bump('new_game')

    def restart(self):
        """Called inside the callback transaction; archive and clone atomically."""
        old = self.game()
        if not old:
            raise RuleError('No hay ninguna partida para reiniciar. Abre /control.')
        for message in self.incomplete():
            self.skip(message['id'], 'Reinicio confirmado por el anfitrión de la casa')
        self.db.execute("UPDATE games SET status='finished' WHERE id=?", (old['id'],))
        self.bump('replayed_finished_game' if old['status'] == 'finished' else 'interrupted_for_restart')
        draft = self.draft(old['title'], json.loads(old['content']))
        self.new_game(draft)
        self.bump('restarted_from', old['id'])

    def button(self, action, payload=''):
        g = self.game()
        token = secrets.token_hex(10)
        self.db.execute('INSERT INTO buttons(token,game,revision,action,payload) VALUES(?,?,?,?,?)',
                        (token, g['id'] if g else 0, g['revision'] if g else 0, action, str(payload)))
        return token

    def consume(self, token):
        row = self.db.execute('SELECT * FROM buttons WHERE token=? AND used=0', (token,)).fetchone()
        g = self.game()
        if not row or (row['game'], row['revision']) != (g['id'] if g else 0, g['revision'] if g else 0):
            raise RuleError('Este botón ha caducado o ya se usó. Abre /control.')
        self.db.execute('UPDATE buttons SET used=1 WHERE token=?', (token,))
        return row['action'], row['payload']

    def register(self, uid, name):
        restored = self.db.execute('DELETE FROM withdrawn_players WHERE player=?', (uid,)).rowcount
        result = self.db.execute('INSERT INTO players VALUES(?,?) ON CONFLICT(id) DO NOTHING', (uid, name))
        return result.rowcount == 1 or bool(restored)

    def leave(self, uid):
        if self.rows("SELECT a.player FROM assignments a JOIN games g ON g.id=a.game WHERE a.player=? AND g.status!='finished'", (uid,)):
            raise RuleError('Tienes un personaje asignado. Pide al anfitrión que libere la asignación o cierre la partida antes de salir.')
        if not self.rows('SELECT id FROM players WHERE id=?', (uid,)):
            return
        self.db.execute('INSERT OR IGNORE INTO withdrawn_players VALUES(?)', (uid,))
        if self.game():
            self.bump('player_left', uid)

    def assignments(self):
        return self.rows('SELECT a.*,p.name FROM assignments a JOIN players p ON p.id=a.player WHERE game=? ORDER BY code', (self.game()['id'],))

    def assign(self, code, player):
        g = self.game()
        if g['status'] != 'preparing' or g['cards']:
            raise RuleError('Las asignaciones están bloqueadas desde la autorización de fichas.')
        if code not in {r['Código'] for r in self.content()['Personajes']}:
            raise RuleError('Personaje desconocido.')
        if not self.rows('SELECT id FROM players WHERE id=?', (player,)):
            raise RuleError('El jugador debe enviar /start primero.')
        if self.rows('SELECT player FROM withdrawn_players WHERE player=?', (player,)):
            raise RuleError('Esta persona salió de la lista. Debe enviar /start para volver.')
        try:
            self.db.execute('INSERT INTO assignments VALUES(?,?,?)', (g['id'], code, player))
        except sqlite3.IntegrityError as exc:
            raise RuleError('El personaje o el jugador ya está asignado. Libera la asignación primero.') from exc
        self.bump('assign', code)

    def unassign(self, code):
        g = self.game()
        if g['status'] != 'preparing' or g['cards']:
            raise RuleError('Las asignaciones están bloqueadas.')
        self.db.execute('DELETE FROM assignments WHERE game=? AND code=?', (g['id'], code))
        self.bump('unassign', code)

    def snapshot(self, phase, records):
        g = self.game()
        assigned = {r['code']: r['player'] for r in self.assignments()}
        if set(assigned) != {r['Código'] for r in self.content()['Personajes']}:
            raise RuleError('Asigna todos los personajes antes de continuar.')
        for position, title, body, recipients in records:
            codes = list(assigned) if recipients == ['TODOS'] else recipients
            cur = self.db.execute('INSERT INTO messages(game,phase,position,title,body,recipients) VALUES(?,?,?,?,?,?)',
                                  (g['id'], phase, position, title, body, ', '.join(codes)))
            self.db.executemany('INSERT INTO deliveries(message,code,player) VALUES(?,?,?)',
                                [(cur.lastrowid, code, assigned[code]) for code in codes])

    def authorize_cards(self, prepare_cards=True):
        g = self.game()
        if g['cards'] or g['status'] != 'preparing':
            raise RuleError('Las fichas ya están autorizadas.')
        self.snapshot(0, [(i, 'Ficha: ' + r['Nombre'], r['Ficha privada'], [r['Código']])
                          for i, r in enumerate(self.content()['Personajes'], 1)] if prepare_cards else [])
        self.db.execute('UPDATE games SET cards=1 WHERE id=?', (g['id'],))
        self.bump('authorize_cards')

    def cancel_preparation(self):
        g = self.game()
        if g['cards'] or g['status'] != 'preparing':
            raise RuleError('Solo se puede descartar una preparación sin fichas autorizadas.')
        self.db.execute("UPDATE games SET status='finished' WHERE id=?", (g['id'],))
        self.bump('cancel_preparation')

    def messages(self, phase=None):
        g = self.game()
        return self.rows('SELECT * FROM messages WHERE game=? AND phase=? ORDER BY position',
                         (g['id'], g['phase'] if phase is None else phase))

    def next_message(self):
        return next((r for r in self.messages() if r['status'] == 'pending'), None)

    def deliveries(self, mid):
        return self.rows('SELECT * FROM deliveries WHERE message=? ORDER BY id', (mid,))

    def incomplete(self):
        return [r for r in self.messages() if r['status'] == 'pending']

    def advance(self, confirmed=False):
        g = self.game()
        if g['status'] == 'finished':
            raise RuleError('La partida ya ha finalizado.')
        if not g['cards']:
            raise RuleError('Autoriza primero las fichas privadas.')
        if self.incomplete() and not confirmed:
            raise RuleError('Confirma los envíos incompletos antes de cerrar la fase.')
        phase = g['phase'] + 1
        for m in self.incomplete():
            self.skip(m['id'], 'Cierre de fase confirmado')
        if phase > len(self.content()['Fases']):
            self.db.execute("UPDATE games SET status='finished' WHERE id=?", (g['id'],))
            self.bump('finish')
            return
        self.snapshot(phase, [(r['Orden'], r['Título admin'], r['Texto'], r['recipients'])
                              for r in self.content()['Mensajes'] if r['Fase'] == phase])
        self.db.execute("UPDATE games SET phase=?,status='active' WHERE id=?", (phase, g['id']))
        self.bump('advance', phase)

    def skip(self, mid, reason='Salto confirmado'):
        if not any(m['id'] == mid and m['status'] == 'pending' for m in self.messages()):
            raise RuleError('Este mensaje ya no está pendiente.')
        self.db.execute("UPDATE messages SET status='skipped' WHERE id=?", (mid,))
        # Preserve confirmed, failed and uncertain outcomes for the audit.
        self.db.execute("UPDATE deliveries SET status='skipped' WHERE message=? AND status='pending'", (mid,))
        self.bump('skip', f'{mid}: {reason}')

    def refresh(self, mid):
        if all(d['status'] in ('sent', 'acknowledged') for d in self.deliveries(mid)):
            self.db.execute("UPDATE messages SET status='completed' WHERE id=? AND status='pending'", (mid,))

    def resolve(self, did, retry):
        m = self.next_message()
        d = self.db.execute('SELECT * FROM deliveries WHERE id=?', (did,)).fetchone()
        if not m or not d or d['message'] != m['id'] or d['status'] != 'uncertain':
            raise RuleError('Esta entrega ya no requiere una decisión.')
        self.db.execute('UPDATE deliveries SET status=?,error=NULL WHERE id=?', ('pending' if retry else 'acknowledged', did))
        self.refresh(m['id'])
        self.bump('resolve_retry' if retry else 'resolve_acknowledged', did)

    def claim(self, mid, retry=False):
        m = self.next_message()
        if self.game()['status'] == 'finished' or not m or m['id'] != mid:
            raise RuleError('Solo se puede enviar el primer mensaje pendiente.')
        deliveries = self.deliveries(mid)
        if any(d['status'] in ('uncertain', 'sending') for d in deliveries):
            raise RuleError('Resuelve primero las entregas inciertas.')
        if not retry and any(d['status'] == 'failed' for d in deliveries):
            raise RuleError('Usa «Reintentar pendientes» para este mensaje.')
        return m

    def report(self, phase=None):
        messages = self.messages(phase)
        deliveries = [d for m in messages for d in self.deliveries(m['id'])]
        return {'messages': len(messages), 'completed': sum(m['status'] == 'completed' for m in messages),
                'skipped': sum(m['status'] == 'skipped' for m in messages),
                'deliveries': len(deliveries), 'sent': sum(d['status'] == 'sent' for d in deliveries),
                'acknowledged': sum(d['status'] == 'acknowledged' for d in deliveries)}
