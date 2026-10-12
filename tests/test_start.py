from unittest.mock import AsyncMock

import pytest
from telegram import Update, User
from telegram.ext import ExtBot

from narrative_bot.bot import build_application


@pytest.mark.asyncio
@pytest.mark.parametrize('uid', [777, 999])
async def test_start_and_join_route_once_and_reply_once(store, monkeypatch, uid):
    monkeypatch.setattr(ExtBot, 'initialize', AsyncMock())
    monkeypatch.setattr(ExtBot, 'shutdown', AsyncMock())
    send = AsyncMock()
    monkeypatch.setattr(ExtBot, 'send_message', send)
    app = build_application('123:OFFLINE_TEST', 999, store)
    monkeypatch.setattr(app.bot, '_bot_user', User(123, 'Bot', True, username='test_bot'))
    await app.initialize()
    before = store.db.total_changes
    for i, text in enumerate(['/start', '/start join', '/start', '/start join']):
        update = Update.de_json({
            'update_id': i + 1,
            'message': {'message_id': i + 1, 'date': 0,
                        'chat': {'id': uid, 'type': 'private'},
                        'from': {'id': uid, 'is_bot': False, 'first_name': f'Name {i}'},
                        'text': text,
                        'entities': [{'type': 'bot_command', 'offset': 0, 'length': 6}]}}, app.bot)
        matches = [handler for handlers in app.handlers.values() for handler in handlers
                   if handler.check_update(update) not in (None, False)]
        assert len(matches) == 1
        assert matches[0].callback.__name__ == 'start'
        send.reset_mock()
        await app.process_update(update)
        send.assert_awaited_once()
    if uid != 999:
        player = store.rows('SELECT * FROM players WHERE id=?', (uid,))
        assert len(player) == 1
        assert player[0]['name'] == 'Name 0'
        assert store.db.total_changes - before == 1
        assert 'Ya estás registrado' in send.call_args.kwargs['text']
    else:
        assert not store.rows('SELECT * FROM players WHERE id=?', (uid,))
    await app.shutdown()


def test_existing_player_registration_does_not_change_assignment(store):
    before = [dict(r) for r in store.assignments()]
    changes = store.db.total_changes
    assert store.register(101, 'Changed name') is False
    assert store.db.total_changes == changes
    assert [dict(r) for r in store.assignments()] == before
