"""Local IT import: validates and stages content without sending anything."""
from pathlib import Path

from .importer import InvalidWorkbook, parse_numbers
from .store import RuleError


def stage_numbers(store, filename):
    path = Path(filename)
    if path.suffix.lower() != '.numbers':
        raise InvalidWorkbook('Archivo, fila 1: usa un archivo .numbers.')
    with path.open('rb') as file:
        content = parse_numbers(file.read(5_000_001))
    title = next((r['Contenido'] for r in content['Guia'] if r['Campo'] == 'Título'), path.stem)
    with store.transaction():
        game = store.game()
        if game and game['status'] != 'finished':
            raise RuleError('Finaliza o descarta la partida actual antes de importar otra.')
        # Replace only the pending draft; existing games are never changed.
        store.db.execute('DELETE FROM drafts')
        store.db.execute('DELETE FROM buttons')
        draft = store.draft(title, content)
    return draft, content
