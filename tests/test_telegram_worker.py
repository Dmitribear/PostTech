"""Telegram tests use fake transports only; no token or real messages are needed."""
import asyncio
import json
from types import SimpleNamespace
from uuid import UUID

import httpx
import pytest
from pydantic import SecretStr

from app.telegram.bot import Bot, Session, TTL
from app.telegram.client import BotConfig, PortalClient, RemoteError, TelegramClient, mutation_key, public_portal_url
from app.telegram.worker import Poller, deliver_notifications

USER = 123
RID = 'e2e506e8-8c41-4a68-aadc-90c915dba240'
CID = 'd7dbeb3c-3665-4f81-ae83-b60b0df77b99'
AID = 'd447b8ed-fb45-43c3-a4b9-03bd1817a33f'
SECRET = 'test-telegram-worker-secret-0123456789'
CONFIG = BotConfig(SecretStr('123456:NOT_A_REAL_TOKEN_abcdefghijkl'), SecretStr(SECRET))


def run(coro):
    return asyncio.run(coro)


def update(text='', *, uid=USER, number=1, callback=None, chat_type='private'):
    message = {'chat': {'id': uid, 'type': chat_type}, 'from': {'id': uid, 'username': 'tester'}, 'text': text}
    if callback is not None:
        return {'update_id': number, 'callback_query': {'id': f'cb{number}', 'from': message['from'], 'message': message, 'data': callback}}
    return {'update_id': number, 'message': message}


class FakeTelegram:
    def __init__(self):
        self.messages, self.calls = [], []
        self.failure = None

    async def send(self, chat, text, markup=None, **kwargs):
        if self.failure:
            raise self.failure
        self.messages.append((chat, text, markup))

    async def call(self, method, data=None, **kwargs):
        self.calls.append((method, data, kwargs))
        if method == 'getMe':
            return {'id': 333}
        if method == 'getWebhookInfo':
            return {'url': ''}
        return True


class FakePortal:
    def __init__(self):
        self.calls = []
        self.link = 'link-one'
        self.role = 'worker'
        self.enabled = True
        self.fail_mutation = False
        self.result = {'id': RID, 'employee_id': 'employee-one', 'request_type': 'leave', 'status': 'pending',
                       'start_date': '2026-11-10', 'end_date': '2026-11-12', 'comment': '', 'can_review': True}
        self.course = {'id': CID, 'title': 'Безопасность', 'description': 'Основы', 'material_markdown': 'Материал',
                       'assignment': {'progress_percent': 0}, 'lessons': [{'id': 'intro', 'title': 'Введение', 'material_markdown': 'Текст урока'}],
                       'quiz': [{'id': 'q1', 'prompt': 'Выберите ответ', 'options': ['Первый', 'Второй']},
                                {'id': 'q2', 'prompt': 'Ещё вопрос', 'options': ['Да', 'Нет']}]}

    async def request(self, method, path, user_id=None, **kwargs):
        self.calls.append((method, path, user_id, kwargs))
        if self.fail_mutation and method not in ('GET',):
            raise RemoteError('Portal', 503)
        if path == '/telegram/status':
            return {'linked': bool(self.link), 'link_id': self.link, 'notifications_enabled': self.enabled}
        if path == '/profile':
            return {'id': 'employee-one', 'full_name': 'Тестовый сотрудник', 'role': self.role, 'vacation_days_remaining': 17}
        if path == '/telegram/consume-link':
            return {'linked': True}
        if path == '/requests/routing':
            return {'can_submit': True}
        if path == '/requests' and method == 'GET':
            return [self.result]
        if path == '/requests' or path.startswith('/requests/') and not path.endswith('.ics'):
            return self.result
        if path.endswith('.ics'):
            return b'BEGIN:VCALENDAR\r\nEND:VCALENDAR\r\n'
        if path == '/ai/ask':
            return {'answer': 'Только сведения из базы.', 'sources': [{'id': AID, 'title': 'Правила', 'version': 'v1', 'url': 'https://untrusted.invalid/ignore'}]}
        if path.startswith('/ai/sources/'):
            return {'id': AID, 'title': 'Правила', 'content': 'Подтверждённый текст', 'source_title': 'Регламент'}
        if path == '/academy/my-courses':
            return [{'course_id': CID, 'course': self.course, 'progress_percent': 0}]
        if path.startswith('/academy/courses/') and path.endswith('/complete'):
            return {'status': 'completed', 'score_percent': 100}
        if path.startswith('/academy/courses/'):
            return self.course
        if path == '/telegram/worker-state':
            return {'bot_id': 333, 'offset': 10}
        if path == '/notifications':
            return []
        return {}


def button(telegram, prefix='ref:'):
    for _, _, markup in reversed(telegram.messages):
        if markup:
            for row in markup.get('inline_keyboard', []):
                for item in row:
                    if item.get('callback_data', '').startswith(prefix):
                        return item['callback_data']
    raise AssertionError(f'No {prefix} button')


def mutations(portal):
    return [call for call in portal.calls if call[0] in ('POST', 'PATCH', 'DELETE')]


@pytest.mark.parametrize('value', ['', 'http://example.com', 'https://localhost:8000', 'https://127.0.0.1',
                                  'https://10.0.0.1', 'https://[::1]', 'https://portal.local', 'https://api',
                                  'https://user:pass@example.com'])
def test_no_unusable_or_credentialed_web_app_url(value):
    assert public_portal_url(value) is None


def test_public_https_web_app_url():
    assert public_portal_url('https://portal.example.com/') == 'https://portal.example.com'


def test_secret_config_and_deterministic_keys(monkeypatch):
    monkeypatch.setenv('TELEGRAM_BOT_TOKEN', CONFIG.token.get_secret_value())
    monkeypatch.setenv('TELEGRAM_WORKER_SECRET', SECRET)
    config = BotConfig.from_env()
    assert SECRET not in repr(config) and CONFIG.token.get_secret_value() not in repr(config)
    key = mutation_key(USER, 8, 'create')
    UUID(key)
    assert key == mutation_key(USER, 8, 'create')
    assert key != mutation_key(USER + 1, 8, 'create')
    monkeypatch.setenv('TELEGRAM_WORKER_SECRET', '')
    with pytest.raises(ValueError, match='Configure'):
        BotConfig.from_env()


def test_transport_auth_json_binary_and_redacted_errors():
    async def scenario():
        captured = []
        def handle(request):
            captured.append(request)
            if request.url.path.endswith('calendar.ics'):
                return httpx.Response(200, content=b'ICS')
            if request.url.path.endswith('/fail'):
                raise httpx.ConnectError(f'LEAK:{SECRET}', request=request)
            if request.url.path.endswith('/private'):
                return httpx.Response(403, json={'detail': f'LEAK:{SECRET}'})
            return httpx.Response(200, json={'ok': True})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
            portal = PortalClient(CONFIG, http)
            assert await portal.request('POST', '/requests', USER, body={'amount': 12}, key='idempotency') == {'ok': True}
            assert captured[0].headers['X-Telegram-Worker-Key'] == SECRET
            assert captured[0].headers['X-Telegram-User-Id'] == str(USER)
            assert captured[0].headers['Idempotency-Key'] == 'idempotency'
            assert json.loads(captured[0].content) == {'amount': 12}
            assert await portal.request('GET', '/requests/calendar.ics', USER, binary=True) == b'ICS'
            await portal.request('GET', '/telegram/worker-state')
            assert 'X-Telegram-User-Id' not in captured[-1].headers
            for path in ('/fail', '/private'):
                with pytest.raises(RemoteError) as error:
                    await portal.request('GET', path, USER)
                assert SECRET not in str(error.value)
            with pytest.raises(ValueError):
                await portal.request('GET', 'https://evil.invalid')
    run(scenario())


def test_telegram_transport_redacts_url_and_never_interprets_markdown():
    async def scenario():
        captured = []
        def handle(request):
            captured.append(request)
            if request.url.path.endswith('/getUpdates'):
                raise httpx.ConnectError(str(request.url), request=request)
            return httpx.Response(200, json={'ok': True, 'result': {'message_id': 1}})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
            tg = TelegramClient(CONFIG, http)
            await tg.send(USER, '<a href="https://example.com">raw</a> **text**')
            payload = json.loads(captured[0].content)
            assert 'parse_mode' not in payload and payload['text'].startswith('<a ')
            with pytest.raises(RemoteError) as error:
                await tg.call('getUpdates')
            assert CONFIG.token.get_secret_value() not in str(error.value)
    run(scenario())


def test_private_chats_only_and_sender_not_chat_controls_identity():
    async def scenario():
        api, tg = FakePortal(), FakeTelegram()
        bot = Bot(api, tg)
        await bot.handle_update(update('/profile', chat_type='supergroup'))
        spoof = update('/profile')
        spoof['message']['chat']['id'] = 999
        await bot.handle_update(spoof)
        assert api.calls == [] and tg.messages == []
        await bot.handle_update(update('/profile'))
        assert all(call[2] == USER for call in api.calls)
        assert 'Сотрудник' in tg.messages[-1][1]
    run(scenario())


def test_link_start_machine_identity_and_menu_public_url():
    async def scenario():
        api, tg = FakePortal(), FakeTelegram()
        bot = Bot(api, tg, 'https://portal.example.com')
        await bot.handle_update(update('/start ' + 'a' * 43))
        consume = next(x for x in api.calls if x[1] == '/telegram/consume-link')
        assert consume[2] is None
        assert consume[3]['body'] == {'code': 'a' * 43, 'telegram_user_id': USER, 'chat_id': USER, 'username': 'tester'}
        assert tg.messages[-1][2]['inline_keyboard'][-1][0]['web_app']['url'] == 'https://portal.example.com'
        await bot.handle_update(update('/stop', number=2))
        assert mutations(api)[-1][0:3] == ('DELETE', '/telegram/link', USER)
        assert USER not in bot.sessions
    run(scenario())


def test_leave_is_only_created_after_confirmation_and_retry_reuses_key():
    async def scenario():
        api, tg = FakePortal(), FakeTelegram()
        bot = Bot(api, tg)
        await bot.handle_update(update(callback='new:leave'))
        await bot.handle_update(update('12.11.2026 10.11.2026', number=2))
        assert bot.sessions[USER].flow['step'] == 'leave_dates'
        await bot.handle_update(update('10.11.2026 12.11.2026', number=3))
        await bot.handle_update(update('Семейные дела', number=4))
        assert not mutations(api)
        confirm = button(tg)
        api.fail_mutation = True
        await bot.handle_update(update(callback=confirm, number=5))
        api.fail_mutation = False
        await bot.handle_update(update(callback=confirm, number=6))
        calls = mutations(api)
        assert len(calls) == 2 and calls[0][3]['key'] == calls[1][3]['key']
        assert calls[1][3]['body'] == {'request_type': 'leave', 'start_date': '2026-11-10', 'end_date': '2026-11-12', 'comment': 'Семейные дела'}
        await bot.handle_update(update(callback=confirm, number=7))
        assert len(mutations(api)) == 2
        assert 'устарела' in tg.messages[-1][1]
    run(scenario())


@pytest.mark.parametrize('amount', ['nan', 'Infinity', '0', '-12', '1000001', '10.123'])
def test_advance_rejects_invalid_amount_without_mutation(amount):
    async def scenario():
        api, tg = FakePortal(), FakeTelegram()
        bot = Bot(api, tg)
        await bot.handle_update(update(callback='new:advance'))
        await bot.handle_update(update(amount, number=2))
        assert bot.sessions[USER].flow['step'] == 'advance_amount'
        assert not mutations(api)
    run(scenario())


def test_restart_expiry_other_user_cancel_and_relink_cannot_confirm_old_draft():
    async def prepare(bot, tg):
        await bot.handle_update(update(callback='new:advance'))
        await bot.handle_update(update('50 000,50', number=2))
        await bot.handle_update(update('-', number=3))
        return button(tg)
    async def scenario():
        api, tg = FakePortal(), FakeTelegram()
        bot = Bot(api, tg)
        confirm = await prepare(bot, tg)
        await bot.handle_update(update(callback=confirm, uid=456, number=4))
        assert not mutations(api)
        await Bot(api, tg).handle_update(update(callback=confirm, number=5))
        assert not mutations(api)
        api.link = 'different-employee-link'
        await bot.handle_update(update(callback=confirm, number=6))
        assert not mutations(api)
        confirm = await prepare(bot, tg)
        bot.sessions[USER].touched -= TTL + 1
        await bot.handle_update(update(callback=confirm, number=7))
        assert not mutations(api)
        confirm = await prepare(bot, tg)
        await bot.handle_update(update('/cancel', number=8))
        await bot.handle_update(update(callback=confirm, number=9))
        assert not mutations(api)
    run(scenario())


def test_manager_review_and_employee_cancel_use_same_api_with_confirmation():
    async def scenario():
        api, tg = FakePortal(), FakeTelegram()
        api.role = 'manager'
        bot = Bot(api, tg)
        await bot.handle_update(update(callback=f'approve:{RID}'))
        assert not mutations(api)
        await bot.handle_update(update(callback=button(tg), number=2))
        approved = mutations(api)[-1]
        assert approved[0:3] == ('PATCH', f'/requests/{RID}/review', USER)
        assert approved[3]['body'] == {'status': 'approved'}
        await bot.handle_update(update(callback=f'reject:{RID}', number=3))
        await bot.handle_update(update('Причина отказа', number=4))
        await bot.handle_update(update(callback=button(tg), number=5))
        assert mutations(api)[-1][3]['body']['reviewer_comment'] == 'Причина отказа'
        await bot.handle_update(update(callback=f'withdraw:{RID}', number=6))
        await bot.handle_update(update(callback=button(tg), number=7))
        assert mutations(api)[-1][0:3] == ('POST', f'/requests/{RID}/cancel', USER)
    run(scenario())


def test_jana_uses_existing_api_and_versioned_source_not_supplied_url():
    async def scenario():
        api, tg = FakePortal(), FakeTelegram()
        bot = Bot(api, tg)
        await bot.handle_update(update('Как оформить отпуск?'))
        ask = next(x for x in api.calls if x[1] == '/ai/ask')
        assert ask[3]['body'] == {'question': 'Как оформить отпуск?'}
        await bot.handle_update(update(callback=button(tg), number=2))
        source = next(x for x in api.calls if x[1].startswith('/ai/sources/'))
        assert source[1] == f'/ai/sources/{AID}' and source[3]['params'] == {'version': 'v1'}
        assert 'Подтверждённый текст' in tg.messages[-1][1]
    run(scenario())


def test_jana_queue_overload_has_clear_message_and_allows_later_retry():
    class BusyPortal(FakePortal):
        overloaded = True

        async def request(self, method, path, user_id=None, **kwargs):
            if path == '/ai/ask' and self.overloaded:
                self.overloaded = False
                raise RemoteError('Portal', 429)
            return await super().request(method, path, user_id, **kwargs)

    async def scenario():
        api, tg = BusyPortal(), FakeTelegram()
        bot = Bot(api, tg)
        await bot.handle_update(update('/ask Как оформить отпуск?'))
        assert 'очередь запросов' in tg.messages[-1][1]
        assert USER not in bot.busy
        await bot.handle_update(update('/ask Как оформить отпуск?', number=2))
        assert tg.messages[-1][1] == 'Только сведения из базы.'
        assert USER not in bot.busy

    run(scenario())


def test_slow_jana_does_not_block_other_user_and_busy_user_gets_feedback():
    async def scenario():
        api, tg = FakePortal(), FakeTelegram()
        started, finish = asyncio.Event(), asyncio.Event()
        original = api.request
        async def request(method, path, user_id=None, **kwargs):
            if path == '/ai/ask':
                started.set()
                await finish.wait()
            return await original(method, path, user_id, **kwargs)
        api.request = request
        bot = Bot(api, tg)
        slow = asyncio.create_task(bot.handle_update(update('Отпуск?')))
        await started.wait()
        await bot.handle_update(update('/profile', uid=456, number=2))
        assert any(chat == 456 and 'Тестовый сотрудник' in text for chat, text, _ in tg.messages)
        await bot.handle_update(update('/profile', number=3))
        assert 'ещё обрабатывается' in tg.messages[-1][1]
        api.link = 'new-link'
        finish.set()
        await slow
        assert 'Подключён другой аккаунт' in tg.messages[-1][1]
        assert not any(text == 'Только сведения из базы.' for _, text, _ in tg.messages)
    run(scenario())


def test_courses_lessons_and_quiz_share_progress_api():
    async def scenario():
        api, tg = FakePortal(), FakeTelegram()
        bot = Bot(api, tg)
        await bot.handle_update(update('/courses'))
        await bot.handle_update(update(callback=f'course:{CID}', number=2))
        await bot.handle_update(update(callback=button(tg), number=3))
        assert 'Текст урока' in tg.messages[-1][1]
        await bot.handle_update(update(callback=button(tg), number=4))
        assert mutations(api)[-1][1] == f'/workspace/courses/{CID}/lessons/intro/complete'
        await bot.handle_update(update(callback=f'quiz:{CID}', number=5))
        first_answer = button(tg)
        await bot.handle_update(update(callback=first_answer, number=6))
        await bot.handle_update(update(callback=first_answer, number=7))
        assert 'Ответ уже выбран' in tg.messages[-1][1]
        await bot.handle_update(update(callback=button(tg), number=8))
        assert 'Отправить тест' in tg.messages[-1][1]
        before = len(mutations(api))
        await bot.handle_update(update(callback=button(tg), number=9))
        submit = mutations(api)[-1]
        assert len(mutations(api)) == before + 1
        assert submit[1] == f'/academy/courses/{CID}/complete'
        assert submit[3]['body'] == {'answers': {'q1': 0, 'q2': 0}}
        UUID(submit[3]['key'])
    run(scenario())


def test_calendar_sends_original_ics_without_model_or_external_sync():
    async def scenario():
        api, tg = FakePortal(), FakeTelegram()
        await Bot(api, tg).handle_update(update('/calendar'))
        method, data, kwargs = tg.calls[-1]
        assert method == 'sendDocument' and kwargs['document'].startswith(b'BEGIN:VCALENDAR')
        assert 'без автосинхронизации' in data['caption']
        assert not mutations(api)
    run(scenario())


def test_permission_errors_are_readable_and_backend_details_not_exposed():
    async def scenario():
        api, tg = FakePortal(), FakeTelegram()
        original = api.request
        async def request(method, path, user_id=None, **kwargs):
            if path == '/profile':
                raise RemoteError('Portal', 403)
            return await original(method, path, user_id, **kwargs)
        api.request = request
        await Bot(api, tg).handle_update(update('/profile'))
        assert 'Нет доступа' in tg.messages[-1][1]
        assert SECRET not in str(tg.messages)
    run(scenario())


def test_offset_does_not_pass_unfinished_update_and_bot_id_scopes_checkpoint():
    async def scenario():
        api, tg = FakePortal(), FakeTelegram()
        gates = {10: asyncio.Event(), 11: asyncio.Event()}
        async def handle(item):
            await gates[item['update_id']].wait()
        poller = Poller(SimpleNamespace(handle_update=handle), api, tg)
        await poller.initialize()
        assert poller.offset == 10 and poller.bot_id == 333
        assert next(x for x in api.calls if x[1] == '/telegram/worker-state')[3]['params'] == {'bot_id': 333}
        poller.accept([{'update_id': 10}, {'update_id': 11}])
        poller.accept([{'update_id': 10}, {'update_id': 11}])
        assert len(poller.pending) == 2
        gates[11].set()
        await asyncio.sleep(0)
        await poller.checkpoint()
        assert poller.offset == 10
        assert not mutations(api)
        gates[10].set()
        await asyncio.sleep(0)
        await poller.checkpoint()
        assert poller.offset == 12 and not poller.pending
        assert mutations(api)[-1][3]['body'] == {'bot_id': 333, 'offset': 12}
    run(scenario())


def test_failed_checkpoint_keeps_finished_updates_for_retry():
    async def scenario():
        api, tg = FakePortal(), FakeTelegram()
        async def handle(item):
            return
        poller = Poller(SimpleNamespace(handle_update=handle), api, tg)
        poller.bot_id = 333
        poller.accept([{'update_id': 20}])
        await asyncio.sleep(0)
        api.fail_mutation = True
        with pytest.raises(RemoteError):
            await poller.checkpoint()
        assert poller.offset == 0 and 20 in poller.pending
        api.fail_mutation = False
        await poller.checkpoint()
        assert poller.offset == 21
    run(scenario())


@pytest.mark.parametrize('linked,enabled,current_link,sending_error,expected', [
    (True, True, 'link-one', None, 'sent'),
    (True, False, 'link-one', None, 'blocked'),
    (False, True, 'link-one', None, 'blocked'),
    (True, True, 'changed-link', None, 'blocked'),
    (True, True, 'link-one', 403, 'blocked'),
    (True, True, 'link-one', 401, 'retry'),
    (True, True, 'link-one', 429, 'retry'),
])
def test_notification_lease_ack_and_link_recheck(linked, enabled, current_link, sending_error, expected):
    async def scenario():
        api, tg = FakePortal(), FakeTelegram()
        row = {'id': RID, 'lease_token': CID, 'link_id': 'link-one', 'telegram_user_id': USER,
               'chat_id': USER, 'title': 'Статус заявки', 'body': 'Заявка согласована', 'request_id': RID}
        original = api.request
        async def request(method, path, user_id=None, **kwargs):
            if path == '/telegram/outbox':
                api.calls.append((method, path, user_id, kwargs))
                return [row]
            if path == '/telegram/status':
                return {'linked': linked, 'notifications_enabled': enabled, 'link_id': current_link}
            return await original(method, path, user_id, **kwargs)
        api.request = request
        if sending_error:
            tg.failure = RemoteError('Telegram', sending_error, 19)
        await deliver_notifications(api, tg)
        ack = mutations(api)[-1]
        assert ack[1] == f'/telegram/outbox/{RID}/ack'
        assert ack[3]['body']['status'] == expected
        assert ack[3]['body']['lease_token'] == CID
        if expected != 'sent':
            assert not tg.messages
        else:
            assert button(tg, 'request:') == f'request:{RID}'
    run(scenario())

@pytest.mark.parametrize('body', [None, [], {'ok': False, 'parameters': None},
                                 {'ok': False, 'error_code': [], 'parameters': {'retry_after': {}}}])
def test_malformed_telegram_responses_are_sanitized(body):
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=body))) as http:
            with pytest.raises(RemoteError) as error:
                await TelegramClient(CONFIG, http).call('sendMessage')
            assert CONFIG.token.get_secret_value() not in str(error.value)
    run(scenario())


def test_unlinked_start_explains_linking_instead_of_role_denial():
    async def scenario():
        api, tg = FakePortal(), FakeTelegram()
        async def request(*args, **kwargs):
            raise RemoteError('Portal', 403)
        api.request = request
        await Bot(api, tg).handle_update(update('/start'))
        assert 'Свяжите аккаунт' in tg.messages[-1][1]
    run(scenario())


def test_native_bot_roundtrip_through_actual_fastapi_routes_and_schemas(monkeypatch):
    """Exercise wire payloads and real worker authentication, with business I/O stubbed."""
    from fastapi import FastAPI
    from app.presentation.http.routes import academy, ai, extensions, requests, telegram
    from app.presentation.http import security
    from app.domain.models import UserContext

    actor = UserContext(id=AID, auth_user_id=RID, role='worker')
    calls = []
    monkeypatch.setattr(security, 'get_settings', lambda: SimpleNamespace(telegram_worker_secret=SecretStr(SECRET)))
    def resolve(uid):
        assert uid == USER
        return actor
    monkeypatch.setattr(telegram.telegram, 'resolve_actor', resolve)
    monkeypatch.setattr(telegram.telegram, 'status', lambda current: {
        'enabled': True, 'linked': True, 'notifications_enabled': True, 'link_id': RID})
    monkeypatch.setattr(requests.workflow, 'request_routing', lambda current: {
        'can_submit': True, 'route': 'manager', 'approvers': [], 'message': None,
        'today': '2026-10-18', 'policy': 'Test policy'})
    def create(current, payload, key):
        assert current == actor and isinstance(key, UUID)
        calls.append(('create', payload.model_dump(mode='json'), str(key)))
        return {'id': RID, 'employee_id': AID, 'request_type': 'leave', 'status': 'pending',
                'start_date': payload.start_date, 'end_date': payload.end_date, 'amount': None,
                'comment': payload.comment, 'reviewer_comment': None, 'reviewed_by': None, 'reviewed_at': None,
                'created_at': '2026-10-18T12:00:00Z', 'updated_at': '2026-10-18T12:00:00Z'}
    monkeypatch.setattr(requests.workflow, 'create_request', create)
    course = FakePortal().course
    monkeypatch.setattr(academy.academy, 'course_details', lambda current, cid: course)
    def lesson(name, params):
        assert name == 'complete_academy_lesson'
        calls.append(('lesson', params))
        return {'progress_percent': 99}
    monkeypatch.setattr(extensions.use_cases, 'execute_command', lesson)
    def quiz(current, cid, answers, key):
        calls.append(('quiz', str(cid), answers, str(key)))
        return {'score_percent': 100, 'status': 'completed'}
    monkeypatch.setattr(academy.academy, 'complete_course', quiz)
    def answer(question, **kwargs):
        calls.append(('ask', question))
        return {'answer': 'Ответ по базе', 'sources': [{'id': AID, 'title': 'Правила', 'version': 'r7',
                 'url': f'/api/v1/ai/sources/{AID}', 'excerpt': 'Цитата'}],
                'grounded': True, 'escalation_suggested': False, 'mode': 'excerpts'}
    monkeypatch.setattr(ai, 'answer_question', answer)
    def source(aid, version=None):
        calls.append(('source', str(aid), version))
        return {'id': aid, 'title': 'Правила', 'content': 'Текст', 'source_title': 'Регламент'}
    monkeypatch.setattr(ai, 'get_source', source)
    monkeypatch.setattr(ai, 'get_settings', lambda: SimpleNamespace(jana_provider='openai'))
    application = FastAPI()
    for route in (requests.router, academy.router, ai.router, extensions.router, telegram.router):
        application.include_router(route, prefix='/api/v1')

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application)) as http:
            api = PortalClient(CONFIG, http)
            tg = FakeTelegram()
            bot = Bot(api, tg)
            await bot.handle_update(update(callback='new:leave', number=1))
            await bot.handle_update(update('10.11.2026 12.11.2026', number=2))
            await bot.handle_update(update('-', number=3))
            assert not calls
            await bot.handle_update(update(callback=button(tg), number=4))
            assert calls[-1][0] == 'create'
            assert calls[-1][1]['start_date'] == '2026-11-10'
            await bot.handle_update(update(callback=f'course:{CID}', number=5))
            await bot.handle_update(update(callback=button(tg), number=6))
            await bot.handle_update(update(callback=button(tg), number=7))
            assert calls[-1] == ('lesson', {'p_actor_id': AID, 'p_course_id': CID, 'p_lesson_id': 'intro'})
            await bot.handle_update(update(callback=f'quiz:{CID}', number=8))
            for number in (9, 10, 11):
                await bot.handle_update(update(callback=button(tg), number=number))
            assert calls[-1][0:3] == ('quiz', CID, {'q1': 0, 'q2': 0})
            await bot.handle_update(update('Где регламент?', number=12))
            await bot.handle_update(update(callback=button(tg), number=13))
            assert calls[-2:] == [('ask', 'Где регламент?'), ('source', AID, 'r7')]
    run(scenario())


def test_start_preserves_random_link_code_that_begins_with_link_prefix():
    async def scenario():
        api, tg = FakePortal(), FakeTelegram()
        code = 'link_' + 'a' * 38
        await Bot(api, tg).handle_update(update('/start ' + code))
        consume = next(call for call in api.calls if call[1] == '/telegram/consume-link')
        assert consume[3]['body']['code'] == code
        assert len(consume[3]['body']['code']) == 43
    run(scenario())


def test_expired_start_link_explains_how_to_create_a_new_one():
    async def scenario():
        api, tg = FakePortal(), FakeTelegram()
        original = api.request
        async def request(method, path, user_id=None, **kwargs):
            if path == '/telegram/consume-link':
                raise RemoteError('Portal', 410)
            return await original(method, path, user_id, **kwargs)
        api.request = request
        await Bot(api, tg).handle_update(update('/start ' + 'a' * 43))
        assert 'истекла или уже использована' in tg.messages[-1][1]
        assert 'Настройки → Telegram' in tg.messages[-1][1]
        assert 'создайте новую ссылку' in tg.messages[-1][1]
        assert not any(call[1] == '/profile' for call in api.calls)
    run(scenario())
