from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from telegram.error import TimedOut

from narrative_bot.bot import Interface
from narrative_bot.delivery import send_next
from narrative_bot.store import Store
from test_engine import phase_one


@pytest.mark.asyncio
async def test_read_confirmation_private_owned_persistent_and_once(store):
    bot = await phase_one(store)
    mid = store.next_message()['id']
    await send_next(store, bot, mid)
    data = bot.send_message.call_args_list[0].kwargs['reply_markup'].inline_keyboard[0][0].callback_data
    delivery = store.deliveries(mid)[0]
    ui = Interface(store, 999)
    context = SimpleNamespace(bot=SimpleNamespace(send_message=AsyncMock()))
    query = SimpleNamespace(data=data, answer=AsyncMock())
    update = SimpleNamespace(callback_query=query, effective_chat=SimpleNamespace(type='private'),
                             effective_user=SimpleNamespace(id=777))
    await ui.callback(update, context)
    assert not store.deliveries(mid)[0]['read_at']
    context.bot.send_message.assert_not_awaited()
    update.effective_user.id = delivery['player']
    update.effective_chat.type = 'group'
    await ui.callback(update, context)
    assert not store.deliveries(mid)[0]['read_at']
    update.effective_chat.type = 'private'
    await ui.callback(update, context)
    await ui.callback(update, context)
    assert store.deliveries(mid)[0]['read_at']
    context.bot.send_message.assert_awaited_once()
    assert context.bot.send_message.call_args.kwargs['chat_id'] == 999
    path = store.db.execute('PRAGMA database_list').fetchone()['file']
    reopened = Store.connect_existing(path)
    try:
        await Interface(reopened, 999).callback(update, context)
        context.bot.send_message.assert_awaited_once()
    finally:
        reopened.db.close()


@pytest.mark.asyncio
async def test_notification_timeout_preserves_read_without_duplicate(store):
    bot = await phase_one(store)
    mid = store.next_message()['id']
    await send_next(store, bot, mid)
    d = store.deliveries(mid)[0]
    token = store.receipt_token(d['id'])
    context = SimpleNamespace(bot=SimpleNamespace(send_message=AsyncMock(side_effect=TimedOut())))
    update = SimpleNamespace(callback_query=SimpleNamespace(data='read:'+token, answer=AsyncMock()),
                             effective_chat=SimpleNamespace(type='private'), effective_user=SimpleNamespace(id=d['player']))
    ui = Interface(store, 999)
    await ui.callback(update, context)
    await ui.callback(update, context)
    context.bot.send_message.assert_awaited_once()
    assert store.deliveries(mid)[0]['read_at']
    assert store.db.execute('SELECT notification FROM read_receipts WHERE delivery=?', (d['id'],)).fetchone()[0] == 'unconfirmed'
