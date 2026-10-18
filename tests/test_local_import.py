import fcntl
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from pathlib import Path
DEMO = Path(__file__).resolve().parents[1] / "examples" / "TEST_BOT_Telegram_2_personajes_historia_independiente.numbers"
from narrative_bot.__main__ import main
from narrative_bot.bot import Interface
from narrative_bot.importer import InvalidWorkbook
from narrative_bot.local_import import stage_numbers
from narrative_bot.store import RuleError, Store
from test_engine import update


def test_import_replaces_only_pending_draft(tmp_path):
    s = Store(tmp_path / 'local.sqlite3')
    first, _ = stage_numbers(s, DEMO)
    token = s.button('import', first)
    second, _ = stage_numbers(s, DEMO)
    assert first != second
    assert len(s.rows('SELECT * FROM drafts')) == 1
    with pytest.raises(RuleError):
        s.consume(token)
    invalid = tmp_path / 'broken.numbers'
    invalid.write_bytes(b'broken')
    with pytest.raises(InvalidWorkbook):
        stage_numbers(s, invalid)
    assert s.rows('SELECT id FROM drafts')[0]['id'] == second
    s.db.close()


def test_existing_game_cannot_be_replaced(store):
    before = store.game()
    with pytest.raises(RuleError):
        stage_numbers(store, DEMO)
    assert store.game() == before
    assert len(store.assignments()) == 3


@pytest.mark.asyncio
async def test_no_telegram_user_can_upload(tmp_path):
    s = Store(tmp_path / 'upload.sqlite3')
    ui = Interface(s, 999)
    for uid in (999, 101):
        u = update(uid)
        u.message.document = SimpleNamespace(get_file=AsyncMock())
        await ui.upload(u, None)
        u.message.document.get_file.assert_not_awaited()
    assert not s.rows('SELECT * FROM drafts')
    assert s.game() is None
    s.db.close()


def test_cli_offline_and_process_lock(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('DATABASE_PATH', str(tmp_path / 'cli.sqlite3'))
    monkeypatch.setenv('ADMIN_TELEGRAM_ID', '')
    monkeypatch.setenv('TELEGRAM_BOT_TOKEN', '')
    monkeypatch.setattr('sys.argv', ['narrative_bot', 'import', str(DEMO)])
    main()
    assert '2 personaggi, 4 fasi, 7 messaggi' in capsys.readouterr().out
    with open(tmp_path / 'cli.sqlite3.lock', 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(SystemExit, match='Fermalo con Ctrl'):
            main()
