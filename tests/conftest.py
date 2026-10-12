from pathlib import Path
import socket

import pytest

from narrative_bot.importer import parse_excel
from narrative_bot.store import Store

DEMO = Path(__file__).resolve().parents[1] / 'examples' / 'Plantilla_juego_Telegram_demo.xlsx'


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError('Network access is forbidden in tests')
    monkeypatch.setattr(socket.socket, 'connect', blocked)
    monkeypatch.setattr(socket.socket, 'connect_ex', blocked)


@pytest.fixture
def content():
    return parse_excel(DEMO.read_bytes())


@pytest.fixture
def store(tmp_path, content):
    s = Store(tmp_path / 'test.sqlite3')
    with s.transaction():
        s.new_game(s.draft('Demo', content))
        for i, r in enumerate(content['Personajes'], 101):
            s.register(i, f'Jugador {i}')
            s.assign(r['Código'], i)
    yield s
    s.db.close()
