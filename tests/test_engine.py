import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from telegram.error import Forbidden, TimedOut

from narrative_bot.bot import Interface
from narrative_bot.delivery import send_next
from narrative_bot.store import RuleError, Store
from conftest import DEMO
from narrative_bot.local_import import stage_numbers


def cards(store):
    with store.transaction():
        store.authorize_cards()


async def phase_one(store):
    cards(store)
    bot = SimpleNamespace(send_message=AsyncMock(return_value=SimpleNamespace(message_id=10)))
    while store.next_message():
        await send_next(store, bot, store.next_message()['id'])
    with store.transaction():
        store.advance()
    bot.send_message.reset_mock()
    return bot


@pytest.mark.asyncio
async def test_order_counts_and_duplicates(store):
    bot = await phase_one(store)
    assert bot.send_message.await_count == 0  # phase opening sends nothing
    messages = store.messages()
    with pytest.raises(RuleError):
        await send_next(store, bot, messages[1]['id'])
    await send_next(store, bot, messages[0]['id'])
    assert bot.send_message.await_count == 3
    report = store.report()
    assert (report['completed'], report['messages'], report['sent'], report['deliveries']) == (1, 4, 3, 6)
    with pytest.raises(RuleError):
        await send_next(store, bot, messages[0]['id'])
    assert bot.send_message.await_count == 3
    assert all(c.kwargs['text'] == store.content()['Mensajes'][0]['Texto'] for c in bot.send_message.call_args_list)


@pytest.mark.asyncio
async def test_partial_failure_only_missing_retried(store):
    bot = await phase_one(store)
    mid = store.next_message()['id']
    bot.send_message.side_effect = [SimpleNamespace(message_id=11), Forbidden('blocked')]
    await send_next(store, bot, mid)
    assert [d['status'] for d in store.deliveries(mid)] == ['sent', 'failed', 'pending']
    with pytest.raises(RuleError):
        await send_next(store, bot, mid)
    bot.send_message.side_effect = None
    bot.send_message.reset_mock()
    await send_next(store, bot, mid, retry=True)
    assert bot.send_message.await_count == 2
    assert store.report()['completed'] == 1


@pytest.mark.asyncio
async def test_uncertain_requires_explicit_decision(store):
    bot = await phase_one(store)
    mid = store.next_message()['id']
    bot.send_message.side_effect = TimedOut()
    await send_next(store, bot, mid)
    assert store.deliveries(mid)[0]['status'] == 'uncertain'
    with pytest.raises(RuleError):
        await send_next(store, bot, mid, retry=True)
    with store.transaction():
        store.resolve(store.deliveries(mid)[0]['id'], retry=False)
    bot.send_message.side_effect = None
    await send_next(store, bot, mid, retry=True)
    assert store.report()['completed'] == 1
    assert store.report()['sent'] == 2
    assert store.report()['acknowledged'] == 1


def test_restart_recovery(store):
    cards(store)
    mid = store.next_message()['id']
    store.db.execute("UPDATE deliveries SET status='sending' WHERE message=?", (mid,))
    path = store.db.execute('PRAGMA database_list').fetchone()['file']
    recovered = Store(path)
    assert recovered.deliveries(mid)[0]['status'] == 'uncertain'
    recovered.db.close()


def test_assignments_unique_and_frozen(store):
    with pytest.raises(RuleError):
        store.assign('MARCO', 102)
    cards(store)
    with pytest.raises(RuleError):
        store.unassign('MARCO')
    with pytest.raises(RuleError):
        store.assign('CLARA', 103)


def test_missing_assignment_blocks_cards(store):
    store.unassign('MARCO')
    with pytest.raises(RuleError):
        cards(store)
    assert not store.messages()


def test_old_callback_and_double_click(store):
    first = store.button('cards')
    second = store.button('cards')
    with store.transaction():
        assert store.consume(first)[0] == 'cards'
    with pytest.raises(RuleError):
        store.consume(first)
    cards(store)
    with pytest.raises(RuleError):
        store.consume(second)


@pytest.mark.asyncio
async def test_phase_confirmation_preserves_counts_and_skips(store):
    bot = await phase_one(store)
    mid = store.next_message()['id']
    bot.send_message.side_effect = TimedOut()
    await send_next(store, bot, mid)
    with pytest.raises(RuleError):
        with store.transaction():
            store.advance()
    with store.transaction():
        store.advance(confirmed=True)
    assert store.report(1)['skipped'] == 4
    assert store.report(1)['deliveries'] == 6
    assert store.deliveries(mid)[0]['status'] == 'uncertain'
    assert store.game()['phase'] == 2
    assert store.report()['sent'] == 0


def update(uid, chat='private', token='anything'):
    message = SimpleNamespace(reply_text=AsyncMock())
    return SimpleNamespace(effective_user=SimpleNamespace(id=uid, full_name='Test'),
                           effective_chat=SimpleNamespace(id=uid, type=chat),
                           effective_message=message, message=message,
                           callback_query=SimpleNamespace(data=token, answer=AsyncMock()))


@pytest.mark.asyncio
async def test_permissions_all_admin_entry_points(store):
    ui = Interface(store, 999)
    context = SimpleNamespace(bot=SimpleNamespace(send_message=AsyncMock()))
    for uid, chat in [(101, 'private'), (999, 'group')]:
        u = update(uid, chat, store.button('cards'))
        await ui.callback(u, context)
        await ui.control(u, context)
        await ui.upload(u, context)
        assert not store.game()['cards']
        context.bot.send_message.assert_not_awaited()
        for call in u.message.reply_text.call_args_list:
            assert 'Ficha' not in call.args[0]
            assert 'María' not in call.args[0]


@pytest.mark.asyncio
async def test_concurrent_callbacks_send_once(store):
    bot = await phase_one(store)
    ui = Interface(store, 999)
    mid = store.next_message()['id']
    a = update(999, token=store.button('send', mid))
    b = update(999, token=store.button('send', mid))
    context = SimpleNamespace(bot=bot)
    await asyncio.gather(ui.callback(a, context), ui.callback(b, context))
    assert bot.send_message.await_count == 3
    assert store.report()['completed'] == 1


@pytest.mark.asyncio
async def test_game_isolation_and_immutable_content(store, content):
    original = store.game()['content']
    cards(store)
    with pytest.raises(RuleError):
        store.new_game(store.draft('Other', content))
    for _ in range(4):
        with store.transaction():
            store.advance(confirmed=True)
    assert store.game()['content'] == original
    old_id = store.game()['id']
    with store.transaction():
        store.new_game(store.draft('New', content))
    assert store.game()['id'] != old_id
    assert not store.assignments()
    assert not store.messages()
    assert store.rows('SELECT * FROM messages WHERE game=?', (old_id,))


@pytest.mark.asyncio
async def test_full_demo_only_whitelisted_player_text(store):
    cards(store)
    bot = SimpleNamespace(send_message=AsyncMock(return_value=SimpleNamespace(message_id=1)))
    story_messages = story_deliveries = 0
    for phase in range(4):
        while store.next_message():
            await send_next(store, bot, store.next_message()['id'])
        r = store.report()
        if phase:
            story_messages += r['completed']
            story_deliveries += r['sent']
        with store.transaction():
            store.advance()
    assert (story_messages, story_deliveries) == (14, 24)
    assert bot.send_message.await_count == 27
    allowed = {r['Ficha privada'] for r in store.content()['Personajes']}
    allowed.update(r['Texto'] for r in store.content()['Mensajes'])
    assert all(c.kwargs['text'] in allowed for c in bot.send_message.call_args_list)
    assert store.game()['status'] == 'finished'


@pytest.mark.asyncio
async def test_import_summary_requires_confirmation(tmp_path):
    s = Store(tmp_path / 'import.sqlite3')
    ui = Interface(s, 999)
    u = update(999)
    from test_numbers import DEMO as NATIVE_DEMO
    stage_numbers(s, NATIVE_DEMO)
    context = SimpleNamespace(bot=SimpleNamespace(send_message=AsyncMock()))
    await ui.control(u, context)
    assert s.game() is None
    call = u.message.reply_text.call_args
    assert 'Mensajes: 7' in call.args[0]
    token = call.kwargs['reply_markup'].inline_keyboard[0][0].callback_data
    await ui.callback(update(999, token=token), context)
    assert s.game()['id'] == 1
    assert not s.messages()
    context.bot.send_message.assert_not_awaited()
    # Reusing the same confirmation cannot create another game.
    await ui.callback(update(999, token=token), context)
    assert len(s.rows('SELECT * FROM games')) == 1
    s.db.close()


@pytest.mark.asyncio
async def test_ui_confirmations_do_not_mutate_until_confirmed(store):
    bot = await phase_one(store)
    ui = Interface(store, 999)
    context = SimpleNamespace(bot=bot)
    u = update(999, token=store.button('advance_confirm'))
    await ui.callback(u, context)
    assert store.game()['phase'] == 1
    text = ''.join(c.args[0] for c in u.message.reply_text.call_args_list)
    assert 'MARCO' in text and 'MARIO' in text and 'CLARA' in text
    token = u.message.reply_text.call_args.kwargs['reply_markup'].inline_keyboard[0][0].callback_data
    await ui.callback(update(999, token=token), context)
    assert store.game()['phase'] == 2
    assert store.report(1)['skipped'] == 4
    bot.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_uncertain_retry_is_explicit_and_preserves_successes(store):
    bot = await phase_one(store)
    mid = store.next_message()['id']
    bot.send_message.side_effect = [SimpleNamespace(message_id=1), TimedOut()]
    await send_next(store, bot, mid)
    did = store.deliveries(mid)[1]['id']
    with store.transaction():
        store.resolve(did, retry=True)
    bot.send_message.side_effect = None
    bot.send_message.reset_mock()
    await send_next(store, bot, mid, retry=True)
    assert bot.send_message.await_count == 2
    assert store.report()['sent'] == 3
    assert store.rows("SELECT * FROM audit WHERE action='resolve_retry'")


def test_snapshot_not_changed_by_new_registration(store):
    cards(store)
    store.advance(confirmed=True)
    before = store.report()
    store.register(777, 'Late arrival')
    assert store.report() == before
    assert all(d['player'] != 777 for m in store.messages() for d in store.deliveries(m['id']))


def test_discard_preparation_and_new_game(store, content):
    with store.transaction():
        store.cancel_preparation()
        store.new_game(store.draft('Corrected', content))
    assert store.game()['title'] == 'Corrected'
    assert not store.assignments()
    assert not store.messages()


@pytest.mark.asyncio
async def test_restart_confirmation_preserves_history_and_frees_characters(store):
    bot = await phase_one(store)
    old = store.game()
    mid = store.next_message()['id']
    bot.send_message.side_effect = [SimpleNamespace(message_id=42), TimedOut()]
    await send_next(store, bot, mid)
    bot.send_message.reset_mock()
    old_button = store.button('send', mid)
    ui = Interface(store, 999)
    context = SimpleNamespace(bot=bot)
    prompt = update(999, token=store.button('restart_confirm'))
    await ui.callback(prompt, context)
    assert store.game()['id'] == old['id']
    keyboard = prompt.message.reply_text.call_args.kwargs['reply_markup'].inline_keyboard
    confirm = keyboard[0][0].callback_data
    # A player cannot use even a valid confirmation token.
    await ui.callback(update(101, token=confirm), context)
    assert store.game()['id'] == old['id']
    await asyncio.gather(ui.callback(update(999, token=confirm), context),
                         ui.callback(update(999, token=confirm), context))
    current = store.game()
    assert current['id'] != old['id']
    assert current['content'] == old['content']
    assert current['status'] == 'preparing'
    assert current['phase'] == 0 and current['cards'] == 0
    assert not store.assignments() and not store.messages()
    assert len(store.rows('SELECT * FROM games')) == 2
    assert len(store.rows('SELECT * FROM players')) == 3
    assert len(store.rows('SELECT * FROM assignments WHERE game=?', (old['id'],))) == 3
    assert store.rows('SELECT status FROM games WHERE id=?', (old['id'],))[0]['status'] == 'finished'
    assert store.rows('SELECT status FROM messages WHERE id=?', (mid,))[0]['status'] == 'skipped'
    assert [d['status'] for d in store.deliveries(mid)] == ['sent', 'uncertain', 'skipped']
    assert store.deliveries(mid)[0]['telegram_id'] == 42
    with pytest.raises(RuleError):
        store.consume(old_button)
    bot.send_message.assert_not_awaited()
    with store.transaction():
        store.assign('MARCO', 101)
        store.unassign('MARCO')


@pytest.mark.asyncio
async def test_restart_cancel_leaves_assignments_locked(store):
    cards(store)
    old = store.game()
    ui = Interface(store, 999)
    prompt = update(999, token=store.button('restart_confirm'))
    await ui.callback(prompt, SimpleNamespace())
    cancel = prompt.message.reply_text.call_args.kwargs['reply_markup'].inline_keyboard[1][0].callback_data
    await ui.callback(update(999, token=cancel), SimpleNamespace())
    assert store.game() == old
    assert len(store.assignments()) == 3
    with pytest.raises(RuleError):
        store.unassign('MARCO')


@pytest.mark.asyncio
async def test_finished_game_has_restart_button(store):
    cards(store)
    for _ in range(4):
        with store.transaction():
            store.advance(confirmed=True)
    old = store.game()
    ui = Interface(store, 999)
    u = update(999)
    context = SimpleNamespace(bot=SimpleNamespace(send_message=AsyncMock()))
    await ui.control(u, context)
    buttons = [b for call in u.message.reply_text.call_args_list
               if call.kwargs.get('reply_markup')
               for row in call.kwargs['reply_markup'].inline_keyboard for b in row]
    token = next(b.callback_data for b in buttons if b.text == 'Volver a jugar')
    prompt = update(999, token=token)
    await ui.callback(prompt, context)
    confirm = prompt.message.reply_text.call_args.kwargs['reply_markup'].inline_keyboard[0][0]
    assert confirm.text == 'Sí, reiniciar'
    await ui.callback(update(999, token=confirm.callback_data), context)
    assert store.game()['id'] != old['id']
    assert store.game()['status'] == 'preparing'
    assert store.game()['content'] == old['content']
    assert not store.assignments()
    context.bot.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_compact_control_and_details(store):
    await phase_one(store)
    ui = Interface(store, 999)
    u = update(999)
    await ui.control(u, None)
    u.message.reply_text.assert_awaited_once()
    call = u.message.reply_text.call_args
    assert len(call.args[0]) < 1800
    assert 'Notas privadas' not in call.args[0]
    buttons = [b for row in call.kwargs['reply_markup'].inline_keyboard for b in row]
    assert [b.text for b in buttons] == ['▶️ Enviar', '📊 Estado']
    detail = next(b for b in buttons if b.text == '📊 Estado')
    other = update(101, token=detail.callback_data)
    await ui.callback(other, None)
    other.message.reply_text.assert_not_awaited()
    admin = update(999, token=detail.callback_data)
    await ui.callback(admin, None)
    assert 'Entregas aceptadas' in admin.message.reply_text.call_args_list[0].args[0]


@pytest.mark.asyncio
async def test_compact_control_uncertain_uses_review(store):
    bot = await phase_one(store)
    bot.send_message.side_effect = TimedOut()
    await send_next(store, bot, store.next_message()['id'])
    u = update(999)
    await Interface(store, 999).control(u, None)
    buttons = [b.text for row in u.message.reply_text.call_args.kwargs['reply_markup'].inline_keyboard for b in row]
    assert '⚠️ Revisar entrega' in buttons
    assert '▶️ Enviar' not in buttons
