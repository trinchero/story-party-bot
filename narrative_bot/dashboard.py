"""Local monitoring and explicitly confirmed lifecycle controls."""
import asyncio
import json
import os
import sqlite3
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
from .store import Store, RuleError

WEB = Path(__file__).with_name('web')


def snapshot(path):
    path = Path(path).resolve()
    if not path.exists():
        return {'game': None, 'phases': [], 'players': [], 'messages': [], 'people': []}
    db = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=2)
    db.row_factory = sqlite3.Row
    try:
        db.execute('PRAGMA query_only=ON')
        db.execute('BEGIN')
        g = db.execute("SELECT g.* FROM games g JOIN settings s ON s.value=g.id WHERE s.key='current'").fetchone()
        draft = None
        if not g or g['status'] == 'finished':
            row = db.execute('SELECT id,title,content FROM drafts ORDER BY rowid DESC LIMIT 1').fetchone()
            if row:
                content = json.loads(row['content'])
                draft = {'id': row['id'], 'title': row['title'], 'characters': len(content['Personajes']), 'phases': len(content['Fases']), 'messages': len(content['Mensajes'])}
        people = [dict(r) for r in db.execute(
            'SELECT p.id,p.name,a.code FROM players p LEFT JOIN assignments a ON a.player=p.id AND a.game=? WHERE p.id NOT IN (SELECT player FROM withdrawn_players) ORDER BY p.name COLLATE NOCASE,p.id',
            (g['id'] if g else -1,))]
        if not g:
            return {'game': None, 'phases': [], 'players': [], 'messages': [], 'people': people, 'draft': draft}
        content = json.loads(g['content'])
        assignments = {r['code']: dict(r) for r in db.execute(
            'SELECT a.code,p.name,p.id FROM assignments a JOIN players p ON p.id=a.player WHERE game=?', (g['id'],))}
        messages = [dict(r) for r in db.execute(
            'SELECT id,phase,position,title,recipients,status FROM messages WHERE game=? ORDER BY phase,position', (g['id'],))]
        deliveries = {}
        for d in db.execute('SELECT d.message,d.code,d.status,d.error,r.read_at FROM deliveries d LEFT JOIN read_receipts r ON r.delivery=d.id JOIN messages m ON m.id=d.message WHERE m.game=? ORDER BY d.id', (g['id'],)):
            deliveries.setdefault(d['message'], []).append(dict(d))
        for m in messages:
            m['deliveries'] = deliveries.get(m['id'], [])
        # Unopened phases have no frozen recipient list yet. Do not invent counts.
        existing = {(m['phase'], m['position']) for m in messages}
        for r in content['Mensajes']:
            if (r['Fase'], r['Orden']) not in existing:
                messages.append({'id': None, 'phase': r['Fase'], 'position': r['Orden'],
                                 'title': r['Título admin'], 'recipients': r['Destinatarios'],
                                 'status': 'not_started', 'deliveries': []})
        messages.sort(key=lambda m: (m['phase'], m['position']))
        phases = [{'number': 0, 'title': 'Preparación · fichas privadas'}] + [
            {'number': r['Fase'], 'title': r['Título']} for r in content['Fases']]
        players = [{'code': r['Código'], 'character': r['Nombre'], 'planned_person': r.get('Persona prevista', ''),
                    'name': assignments.get(r['Código'], {}).get('name'),
                    'person_id': assignments.get(r['Código'], {}).get('id'), 'counts': {}}
                   for r in content['Personajes']]
        for p in players:
            for phase in phases:
                states = [d['status'] for m in messages if m['phase'] == phase['number']
                          for d in m['deliveries'] if d['code'] == p['code']]
                p['counts'][str(phase['number'])] = dict(Counter(states))
        first = next((r for r in content['Mensajes'] if r['Fase'] == 1 and r['Orden'] == 1), None)
        preview = {'title': first['Título admin'], 'recipients': first['Destinatarios'], 'text': first['Texto']} if first else None
        return {'game': {'id': g['id'], 'title': g['title'], 'phase': g['phase'], 'status': g['status'], 'revision': g['revision'], 'assignments_open': g['status'] == 'preparing' and not g['cards']},
                'phases': phases, 'players': players, 'messages': messages, 'people': people, 'draft': draft, 'first_message': preview}
    finally:
        db.close()


def control_game(path, action, game_id, revision, person=None, draft=None, code=None, skip_pending=False, sender=None):
    if action not in ('close', 'restart', 'remove_person', 'start', 'assign', 'unassign', 'confirm_roles', 'begin'):
        raise RuleError('Acción desconocida.')
    if action == 'begin':
        return begin_game(path, game_id, revision, skip_pending, sender)
    store = Store.connect_existing(path)
    try:
        with store.operation(), store.transaction():
            g = store.game()
            if (g['id'] if g else 0, g['revision'] if g else 0) != (game_id, revision):
                raise RuleError('La partida ha cambiado. Actualiza y confirma de nuevo.')
            if action == 'start':
                if not isinstance(draft, str):
                    raise RuleError('Selecciona una historia importada.')
                store.new_game(draft)
                return
            if action == 'remove_person':
                if type(person) is not int:
                    raise RuleError('Persona no válida.')
                store.leave(person)
                return
            if not g:
                raise RuleError('No hay ninguna partida.')
            if action == 'confirm_roles':
                store.authorize_cards(prepare_cards=False)
                return
            if action in ('assign', 'unassign'):
                if type(person) is not int or not isinstance(code, str):
                    raise RuleError('Selecciona una persona y un personaje.')
                if action == 'assign':
                    if str(person) == os.getenv('ADMIN_TELEGRAM_ID', '').strip():
                        raise RuleError('El anfitrión dirige la partida y no puede recibir un personaje.')
                    store.assign(code, person)
                else:
                    if not any(a['code'] == code and a['player'] == person for a in store.assignments()):
                        raise RuleError('La asignación ha cambiado. Actualiza la página.')
                    store.unassign(code)
                return
            if store.rows("SELECT d.id FROM deliveries d JOIN messages m ON m.id=d.message WHERE m.game=? AND d.status='sending'", (g['id'],)):
                raise RuleError('Hay un envío en curso. Espera antes de cerrar o reiniciar.')
            if action == 'close':
                store.close_game()
            else:
                store.restart()
    finally:
        store.db.close()


async def send_initial(store, mid):
    from telegram import Bot
    from .delivery import _send_next
    async with Bot(os.environ['TELEGRAM_BOT_TOKEN'].strip()) as bot:
        await _send_next(store, bot, mid)


def begin_game(path, game_id, revision, skip_pending=False, sender=None):
    if sender is None and not os.getenv('TELEGRAM_BOT_TOKEN', '').strip():
        raise RuleError('Configura el token del bot antes de iniciar la partida.')
    store = Store.connect_existing(path)
    try:
        with store.operation():
            with store.transaction():
                g = store.game()
                if not g or (g['id'], g['revision']) != (game_id, revision):
                    raise RuleError('La partida ha cambiado. Actualiza la página.')
                if g['phase'] != 0 or g['status'] != 'preparing':
                    raise RuleError('La partida ya ha comenzado o está cerrada.')
                if store.rows("SELECT d.id FROM deliveries d JOIN messages m ON m.id=d.message WHERE m.game=? AND d.status='sending'", (game_id,)):
                    raise RuleError('Hay un envío en curso. Espera antes de iniciar.')
                store.advance(confirmed=True)
                mid = store.next_message()['id']
            try:
                asyncio.run((sender or send_initial)(store, mid))
            except Exception:
                # Never retry an ambiguous delivery or expose exception credentials.
                with store.transaction():
                    store.db.execute("UPDATE deliveries SET status='uncertain',error='Interrupción durante el envío' WHERE message=? AND status='sending'", (mid,))
                raise RuleError('Fase 1 iniciada. Revisa el primer mensaje en Mensajes antes de reintentar desde Telegram.') from None
    finally:
        store.db.close()


def make_server(path, port=8080):

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # Never log authorization values or user-controlled request paths.

        def reply(self, code, body, mime='application/json'):
            self.send_response(code)
            self.send_header('Content-Type', mime + '; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            # Loopback binding plus Host validation protects against DNS rebinding.
            valid_hosts = {f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}'}
            if self.headers.get('Host') not in valid_hosts:
                return self.reply(403, b'{"error":"Host no permitido"}')
            route = urlsplit(self.path).path
            if route == '/api/state':
                try:
                    data = snapshot(path)
                except (sqlite3.Error, ValueError, KeyError):
                    return self.reply(503, b'{"error":"No se puede leer el estado. Reintenta en unos segundos."}')
                return self.reply(200, json.dumps(data, ensure_ascii=False).encode())
            assets = {'/': ('index.html', 'text/html'), '/app.js': ('app.js', 'text/javascript'), '/style.css': ('style.css', 'text/css')}
            if route not in assets:
                return self.reply(404, b'{}')
            file, mime = assets[route]
            self.reply(200, (WEB / file).read_bytes(), mime)

        def do_POST(self):
            host = self.headers.get('Host')
            if host not in {f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}'} or self.headers.get('Origin') != f'http://{host}':
                return self.reply(403, b'{"error":"Origen no permitido"}')
            if self.path != '/api/control':
                return self.reply(404, b'{}')
            if self.headers.get('Content-Type') != 'application/json':
                return self.reply(415, b'{}')
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= 1024:
                    raise ValueError()
                payload = json.loads(self.rfile.read(size))
                if not isinstance(payload, dict) or payload.get('confirmed') is not True:
                    raise ValueError()
                if type(payload.get('game')) is not int or type(payload.get('revision')) is not int:
                    raise ValueError()
                control_game(path, payload.get('action'), payload['game'], payload['revision'], payload.get('person'), payload.get('draft'), payload.get('code'), payload.get('skip_pending', False))
            except RuleError as exc:
                return self.reply(409, json.dumps({'error': str(exc)}).encode())
            except (ValueError, TypeError):
                return self.reply(400, b'{"error":"Confirmacion no valida"}')
            except sqlite3.Error:
                return self.reply(503, b'{"error":"Base de datos no disponible"}')
            self.reply(200, b'{"ok":true}')

    return ThreadingHTTPServer(('127.0.0.1', port), Handler)


def serve(path, port=8080):
    if Path(path).exists():
        Store.connect_existing(path).db.close()
    server = make_server(path, port)
    print(f'Dashboard locale: http://127.0.0.1:{server.server_port}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
