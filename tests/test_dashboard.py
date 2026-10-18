import http.client
import json
import socket
import threading
import pytest
from pathlib import Path

from narrative_bot.dashboard import make_server, snapshot, control_game
from narrative_bot.store import RuleError

CONNECT = socket.socket.connect


def test_snapshot_is_read_only_and_keeps_uncertain_separate(store):
    store.authorize_cards()
    mid = store.next_message()['id']
    store.db.execute("UPDATE deliveries SET status='sending' WHERE message=?", (mid,))
    path = store.db.execute('PRAGMA database_list').fetchone()['file']
    before = store.db.total_changes
    data = snapshot(path)
    assert data['messages'][0]['deliveries'][0]['status'] == 'sending'
    assert store.deliveries(mid)[0]['status'] == 'sending'
    assert store.db.total_changes == before
    assert len(data['players']) == 3
    assert all(m['status'] == 'not_started' for m in data['messages'] if m['phase'] > 0)
    raw = json.dumps(data)
    assert 'Ficha privada' not in raw
    assert 'Guia' not in raw and 'body' not in raw and 'telegram_id' not in raw
    for r in store.content()['Personajes']:
        assert r['Ficha privada'] not in raw


def test_counts_and_frozen_recipients(store):
    store.authorize_cards()
    store.advance(confirmed=True)
    mid = store.next_message()['id']
    ds = store.deliveries(mid)
    for d, status in zip(ds, ['sent', 'failed', 'uncertain']):
        store.db.execute('UPDATE deliveries SET status=? WHERE id=?', (status, d['id']))
    store.register(777, 'Not playing')
    data = snapshot(store.db.execute('PRAGMA database_list').fetchone()['file'])
    assert len(data['players']) == 3
    counts = [p['counts']['1'] for p in data['players']]
    assert sum(sum(c.values()) for c in counts) == 6
    assert sum(c.get('sent', 0) for c in counts) == 1
    assert sum(c.get('failed', 0) for c in counts) == 1
    assert sum(c.get('uncertain', 0) for c in counts) == 1


def test_missing_database_is_not_created(tmp_path):
    path = tmp_path / 'missing.sqlite3'
    assert snapshot(path)['game'] is None
    assert not path.exists()


def test_start_preview_matches_first_story_message_without_admin_notes(store):
    path = store.db.execute('PRAGMA database_list').fetchone()['file']
    first = next(r for r in store.content()['Mensajes'] if r['Fase'] == 1 and r['Orden'] == 1)
    assert snapshot(path)['first_message'] == {
        'title': first['Título admin'], 'recipients': first['Destinatarios'], 'text': first['Texto']}


def test_begin_timeout_stops_first_message_without_resending(store):
    from unittest.mock import AsyncMock
    from types import SimpleNamespace
    from narrative_bot.delivery import _send_next
    bot = SimpleNamespace(send_message=AsyncMock(side_effect=TimeoutError))
    async def sender(s, mid):
        await _send_next(s, bot, mid)
    store.authorize_cards()
    g = store.game()
    path = store.db.execute('PRAGMA database_list').fetchone()['file']
    control_game(path, 'begin', g['id'], g['revision'], skip_pending=True, sender=sender)
    first = store.messages()[0]
    assert [d['status'] for d in store.deliveries(first['id'])] == ['uncertain', 'pending', 'pending']
    with pytest.raises(RuleError):
        control_game(path, 'begin', g['id'], g['revision'], skip_pending=True, sender=sender)
    assert bot.send_message.await_count == 1


def test_web_begin_requires_roles_but_not_legacy_cards(store):
    from unittest.mock import AsyncMock
    from types import SimpleNamespace
    from narrative_bot.delivery import _send_next
    bot = SimpleNamespace(send_message=AsyncMock(return_value=SimpleNamespace(message_id=1)))
    async def sender(s, mid):
        await _send_next(s, bot, mid)
    path = store.db.execute('PRAGMA database_list').fetchone()['file']
    g = store.game()
    with pytest.raises(RuleError):
        control_game(path, 'begin', g['id'], g['revision'], sender=sender)
    store.authorize_cards()
    g = store.game()
    assert store.game()['phase'] == 0
    control_game(path, 'begin', g['id'], g['revision'], skip_pending=True, sender=sender)
    assert store.game()['phase'] == 1
    messages = store.messages()
    assert messages[0]['status'] == 'completed'
    assert all(m['status'] == 'pending' for m in messages[1:])
    assert bot.send_message.await_count == 3
    assert all(d['status'] == 'sent' for d in store.deliveries(messages[0]['id']))
    assert all(m['status'] == 'skipped' for m in store.messages(0))
    g = store.game()
    with pytest.raises(RuleError):
        control_game(path, 'begin', g['id'], g['revision'], skip_pending=True, sender=sender)


def test_confirm_roles_requires_every_role_and_locks_until_restart(store):
    path = store.db.execute('PRAGMA database_list').fetchone()['file']
    code = store.content()['Personajes'][0]['Código']
    store.unassign(code)
    g = store.game()
    with pytest.raises(RuleError, match='todos'):
        control_game(path, 'confirm_roles', g['id'], g['revision'])
    assert not store.messages()
    store.assign(code, 101)
    g = store.game()
    control_game(path, 'confirm_roles', g['id'], g['revision'])
    assert not snapshot(path)['game']['assignments_open']
    assert not store.messages(0)
    assert all(d['status'] == 'pending' for m in store.messages() for d in store.deliveries(m['id']))
    with pytest.raises(RuleError):
        store.unassign(code)
    with pytest.raises(RuleError):
        control_game(path, 'confirm_roles', g['id'], g['revision'])
    with store.transaction():
        store.close_game()
        store.restart()
    assert snapshot(path)['game']['assignments_open']
    assert not store.assignments()


def test_web_assignments_respect_uniqueness_admin_and_card_lock(store, monkeypatch):
    path = store.db.execute('PRAGMA database_list').fetchone()['file']
    code = store.content()['Personajes'][0]['Código']
    def act(action, uid=101):
        g = store.game()
        control_game(path, action, g['id'], g['revision'], person=uid, code=code)
    assert snapshot(path)['game']['assignments_open']
    act('unassign')
    monkeypatch.setenv('ADMIN_TELEGRAM_ID', '101')
    with pytest.raises(RuleError, match='anfitrión'):
        act('assign')
    monkeypatch.setenv('ADMIN_TELEGRAM_ID', '999')
    act('assign')
    with pytest.raises(RuleError):
        act('assign', 102)
    store.authorize_cards()
    assert not snapshot(path)['game']['assignments_open']
    with pytest.raises(RuleError, match='bloqueadas'):
        act('unassign')
    assert len(store.assignments()) == 3


def test_start_draft_requires_closed_game_and_rejects_duplicate(store, content):
    path = store.db.execute('PRAGMA database_list').fetchone()['file']
    draft = store.draft('New story', content)
    g = store.game()
    with pytest.raises(RuleError):
        control_game(path, 'start', g['id'], g['revision'], draft=draft)
    with store.transaction():
        store.close_game()
    g = store.game()
    summary = snapshot(path)['draft']
    assert summary['id'] == draft and summary['characters'] == 3
    assert 'content' not in summary
    control_game(path, 'start', g['id'], g['revision'], draft=draft)
    assert store.game()['title'] == 'New story'
    assert store.game()['phase'] == 0 and not store.game()['cards']
    assert not store.messages() and not store.assignments()
    assert snapshot(path)['draft'] is None
    with pytest.raises(RuleError):
        control_game(path, 'start', g['id'], g['revision'], draft=draft)


def test_leave_blocks_assigned_players_and_preserves_history(store):
    path = store.db.execute('PRAGMA database_list').fetchone()['file']
    g = store.game()
    with pytest.raises(RuleError, match='personaje asignado'):
        control_game(path, 'remove_person', g['id'], g['revision'], 101)
    store.register(777, 'Available')
    control_game(path, 'remove_person', g['id'], g['revision'], 777)
    assert 777 not in [p['id'] for p in snapshot(path)['people']]
    assert store.register(777, 'Available')
    assert 777 in [p['id'] for p in snapshot(path)['people']]
    with store.transaction():
        store.close_game()
        store.leave(101)
    assert 101 not in [p['id'] for p in snapshot(path)['people']]
    assert any(a['player'] == 101 for a in store.assignments())
    with store.transaction():
        store.restart()
        with pytest.raises(RuleError, match='salió'):
            store.assign(store.content()['Personajes'][0]['Código'], 101)


def test_roster_includes_unassigned_people_and_only_current_assignments(store):
    path = store.db.execute('PRAGMA database_list').fetchone()['file']
    store.register(999, 'Jugador 101')  # Same name, different identity.
    data = snapshot(path)
    assert len(data['people']) == 4
    assert next(p for p in data['people'] if p['id'] == 999)['code'] is None
    assert all(p['person_id'] is not None for p in data['players'])
    with store.transaction():
        store.restart()
    data = snapshot(path)
    assert len(data['people']) == 4
    assert all(p['code'] is None for p in data['people'])
    assert all(p['person_id'] is None for p in data['players'])


def test_http_local_access_and_confirmed_controls(store, monkeypatch):
    # Only this local HTTP test may connect, and only to our loopback server.
    path = store.db.execute('PRAGMA database_list').fetchone()['file']
    server = make_server(path, 0)
    def local_connect(sock, address):
        assert address == ('127.0.0.1', server.server_port)
        return CONNECT(sock, address)
    monkeypatch.setattr(socket.socket, 'connect', local_connect)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    def request(path, headers=None, method='GET', body=None):
        conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=3)
        conn.request(method, path, headers=headers or {}, body=body)
        res = conn.getresponse()
        body = res.read()
        conn.close()
        return res.status, body
    try:
        assert request('/')[0] == 200
        assert request('/api/state')[0] == 200
        assert request('/api/state', {'Host': 'evil.example'})[0] == 403
        assert request('/api/control', method='POST')[0] == 403
        assert request('/../.env')[0] == 404
        headers = {'Origin': f'http://127.0.0.1:{server.server_port}', 'Content-Type': 'application/json'}
        g = store.game()
        payload = {'action': 'close', 'game': g['id'], 'revision': g['revision']}
        assert request('/api/control', headers, 'POST', json.dumps(payload))[0] == 400
        payload['confirmed'] = True
        assert request('/api/control', {**headers, 'Origin': 'https://evil.example'}, 'POST', json.dumps(payload))[0] == 403
        assert store.game()['status'] == 'preparing'
        assert request('/api/control', headers, 'POST', json.dumps(payload))[0] == 200
        assert store.game()['status'] == 'finished'
        assert request('/api/control', headers, 'POST', json.dumps(payload))[0] == 409
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_web_close_preserves_history_and_rejects_stale_click(store):
    store.authorize_cards()
    mid = store.next_message()['id']
    store.db.execute("UPDATE deliveries SET status='uncertain' WHERE message=?", (mid,))
    g = store.game()
    path = store.db.execute('PRAGMA database_list').fetchone()['file']
    control_game(path, 'close', g['id'], g['revision'])
    assert store.game()['status'] == 'finished'
    assert store.deliveries(mid)[0]['status'] == 'uncertain'
    assert all(m['status'] == 'skipped' for m in store.messages())
    with pytest.raises(RuleError, match='cambiado'):
        control_game(path, 'restart', g['id'], g['revision'])


def test_web_restart_separates_game_and_assignments(store):
    g = store.game()
    path = store.db.execute('PRAGMA database_list').fetchone()['file']
    control_game(path, 'restart', g['id'], g['revision'])
    assert store.game()['id'] != g['id']
    assert store.game()['content'] == g['content']
    assert store.game()['status'] == 'preparing'
    assert not store.assignments()
    assert len(store.rows('SELECT * FROM players')) == 3
    assert len(store.rows('SELECT * FROM assignments WHERE game=?', (g['id'],))) == 3


def test_web_control_rejects_inflight_send_and_shared_lock(store):
    path = store.db.execute('PRAGMA database_list').fetchone()['file']
    store.authorize_cards()
    g = store.game()
    with store.operation(), pytest.raises(RuleError, match='operación en curso'):
        control_game(path, 'close', g['id'], g['revision'])
    mid = store.next_message()['id']
    store.db.execute("UPDATE deliveries SET status='sending' WHERE message=?", (mid,))
    with pytest.raises(RuleError, match='envío en curso'):
        control_game(path, 'restart', g['id'], g['revision'])
    assert store.deliveries(mid)[0]['status'] == 'sending'
    assert store.game()['status'] == 'preparing'
