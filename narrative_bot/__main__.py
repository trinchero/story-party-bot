import fcntl
import argparse
import logging
import os
from pathlib import Path

from dotenv import load_dotenv

from .bot import build_application
from .store import Store
from .store import RuleError
from .importer import InvalidWorkbook
from .local_import import stage_numbers


def main():
    parser = argparse.ArgumentParser(description='Bot narrativo e importazione Numbers per IT.')
    commands = parser.add_subparsers(dest='command')
    importer = commands.add_parser('import', help='Importa un Numbers locale da confermare in Telegram')
    importer.add_argument('file', help='Percorso del file .numbers')
    dashboard = commands.add_parser('dashboard', help='Dashboard web locale di monitoraggio')
    dashboard.add_argument('--port', type=int, default=8080)
    args = parser.parse_args()
    load_dotenv()
    if args.command == 'dashboard':
        from .dashboard import serve
        serve(Path(os.getenv('DATABASE_PATH', 'data/game.sqlite3')).expanduser().resolve(), args.port)
        return
    token = os.getenv('TELEGRAM_BOT_TOKEN', '').strip()
    admin_id = 0
    if args.command != 'import':
        try:
            admin_id = int(os.getenv('ADMIN_TELEGRAM_ID', '0'))
        except ValueError:
            raise SystemExit('ADMIN_TELEGRAM_ID deve essere un ID numerico.') from None
        if not token or admin_id <= 0:
            raise SystemExit('Configura TELEGRAM_BOT_TOKEN e ADMIN_TELEGRAM_ID in .env.')
    os.umask(0o077)
    path = Path(os.getenv('DATABASE_PATH', 'data/game.sqlite3')).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    # Held for the full process lifetime; also prevents incorrect crash recovery
    # by another process while a send is still running.
    with open(str(path) + '.lock', 'a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit('Il bot sta usando questo database. Fermalo con Ctrl+C prima di importare o avviare un’altra istanza.') from None
        logging.basicConfig(level=logging.WARNING, format='%(levelname)s %(name)s: %(message)s')
        logging.getLogger('httpx').disabled = True
        logging.getLogger('httpcore').disabled = True
        store = Store(path)
        try:
            if args.command == 'import':
                try:
                    _, content = stage_numbers(store, args.file)
                except (OSError, InvalidWorkbook, RuleError) as exc:
                    raise SystemExit(str(exc)) from None
                print(f"Numbers validato: {len(content['Personajes'])} personaggi, "
                      f"{len(content['Fases'])} fasi, {len(content['Mensajes'])} messaggi.")
                print("Importazione pronta. Avvia il bot; l’anfitrione della casa può confermare il riepilogo con /control. Nessun messaggio inviato.")
                return
            build_application(token, admin_id, store).run_polling(drop_pending_updates=False)
        finally:
            store.db.close()


if __name__ == '__main__':
    main()
