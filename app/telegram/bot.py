"""Native private-chat UI. All business decisions stay in the existing portal API.

Only explicitly confirmed drafts mutate HR data. Drafts and callback capabilities
expire and intentionally do not survive restart; deterministic keys make a retry
of an already submitted command safe. Telegram is not an authentication authority.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
import secrets
import time
from urllib.parse import quote

from app.telegram.client import RemoteError, mutation_key, public_portal_url

STATUS = {'pending': 'У руководителя', 'pending_hr': 'У HR', 'pending_director': 'У директора',
          'approved': 'Согласовано', 'rejected': 'Отклонено', 'cancelled': 'Отменено'}
ROLE = {'worker': 'Сотрудник', 'employee': 'Сотрудник', 'manager': 'Руководитель', 'director': 'Директор', 'hr_admin': 'HR'}
PAGE = 10
TTL = 900


def keyboard(rows):
    return {'inline_keyboard': [[{'text': title, 'callback_data': data} for title, data in row] for row in rows]}


def short_request(row):
    detail = f"{row.get('start_date')} — {row.get('end_date')}" if row.get('request_type') == 'leave' else f"{row.get('amount')} ₸"
    kind = 'Отпуск' if row.get('request_type') == 'leave' else 'Аванс'
    return f"{kind}: {detail}\nСтатус: {STATUS.get(row.get('status'), row.get('status', '—'))}"


def parse_date(value):
    for fmt in ('%d.%m.%Y', '%Y-%m-%d'):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            pass
    raise ValueError('Введите две даты: 10.11.2026 12.11.2026.')


@dataclass
class Session:
    link_id: str | None = None
    flow: dict | None = None
    refs: dict = field(default_factory=dict)
    touched: float = field(default_factory=time.monotonic)

    def ref(self, value):
        if len(self.refs) >= 150:
            self.refs.pop(next(iter(self.refs)))
        token = secrets.token_hex(6)
        self.refs[token] = (time.monotonic() + TTL, value)
        return token

    def lookup(self, token):
        item = self.refs.get(token)
        return item[1] if item and item[0] > time.monotonic() else None


class Bot:
    def __init__(self, portal, telegram, portal_url=''):
        self.api, self.tg = portal, telegram
        self.portal_url = public_portal_url(portal_url)
        self.sessions: dict[int, Session] = {}
        self.busy: set[int] = set()

    def session(self, uid):
        now = time.monotonic()
        self.sessions = {key: value for key, value in self.sessions.items()
                         if now - value.touched < TTL or (key in self.busy and key != uid)}
        session = self.sessions.setdefault(uid, Session())
        session.touched = now
        return session

    async def sync_link(self, uid, session):
        try:
            current = await self.api.request('GET', '/telegram/status', uid)
        except RemoteError as exc:
            if exc.status == 403:
                raise RemoteError('Portal', 401) from None
            raise
        if not current.get('linked') or not current.get('link_id'):
            raise RemoteError('Portal', 401)
        if session.link_id != current['link_id']:
            session.flow = None
            session.refs.clear()
            session.link_id = current['link_id']
        return current['link_id']

    async def menu(self, chat, uid):
        profile = await self.api.request('GET', '/profile', uid)
        rows = [[('Мой профиль', 'profile'), ('Мои заявки', 'requests:mine:0')],
                [('Отпуск', 'new:leave'), ('Аванс', 'new:advance')],
                [('Спросить Jana', 'ask'), ('Мои курсы', 'courses:0')],
                [('Календарь .ics', 'calendar'), ('Уведомления', 'notifications:0')],
                [('Обращения в HR', 'tickets')]]
        if profile.get('role') in ('manager', 'director', 'hr_admin'):
            rows.append([('На согласование', 'requests:review:0'), ('Моя команда', 'team')])
        markup = keyboard(rows)
        if self.portal_url:
            markup['inline_keyboard'].append([{'text': 'Открыть весь портал', 'web_app': {'url': self.portal_url}}])
        await self.tg.send(chat, f"JanaМен · {profile.get('full_name', '')}\nВыберите раздел или напишите вопрос Jana. /cancel — отменить ввод, /stop — отключить Telegram.", markup)

    async def handle_update(self, update):
        callback = update.get('callback_query')
        message = callback.get('message', {}) if callback else update.get('message', {})
        sender = callback.get('from', {}) if callback else message.get('from', {})
        chat = message.get('chat', {})
        uid, chat_id = sender.get('id'), chat.get('id')
        # Never reveal HR data in group chats, channels, inline or business messages.
        if chat.get('type') != 'private' or not isinstance(uid, int) or uid <= 0 or chat_id != uid or sender.get('is_bot'):
            if callback:
                try:
                    await self.tg.call('answerCallbackQuery', {'callback_query_id': callback['id'], 'text': 'Откройте личный чат с ботом.'})
                except RemoteError as exc:
                    if exc.status not in (400, 403):
                        raise
            return
        if callback:
            try:
                await self.tg.call('answerCallbackQuery', {'callback_query_id': callback['id']})
            except RemoteError as exc:
                if exc.status != 400:  # A replay may have an expired callback query.
                    raise
        if uid in self.busy:
            await self.tg.send(chat_id, 'Предыдущий запрос ещё обрабатывается. Дождитесь ответа и повторите действие.')
            return
        self.busy.add(uid)
        try:
            session = self.session(uid)
            text = message.get('text', '').strip()
            command, _, payload = text.partition(' ')
            if callback or not (command.split('@')[0].lower() == '/start' and payload):
                await self.sync_link(uid, session)
            if callback:
                await self.callback(chat_id, uid, update['update_id'], callback.get('data', ''), session)
            else:
                await self.message(chat_id, uid, update['update_id'], message.get('text', ''), sender, session)
        except RemoteError as exc:
            if str(exc).startswith('Telegram'):
                # Retry delivery rather than acknowledging an update silently.
                if exc.status == 403:  # User blocked the bot; do not jam other updates.
                    return
                raise
            messages = {401: 'Свяжите аккаунт: на сайте откройте «Telegram», создайте ссылку и нажмите Start в боте.',
                        403: 'Нет доступа к этому действию. Права такие же, как на сайте.',
                        404: 'Запись не найдена или больше недоступна.',
                        409: 'Данные уже изменились или действие сейчас недоступно. Обновите карточку на сайте или через /menu.',
                        410: 'Ссылка подключения истекла или уже использована. На сайте откройте «Настройки → Telegram», создайте новую ссылку и нажмите Start.',
                        422: 'Проверьте введённые данные и правила на сайте. /cancel — начать заново.'}
            await self.tg.send(chat_id, messages.get(exc.status, 'Сервис временно недоступен. Повторите действие позже; подтверждённые операции не дублируются.'))
        except (ValueError, KeyError, TypeError):
            await self.tg.send(chat_id, 'Не удалось прочитать данные. Откройте /menu или начните ввод заново через /cancel.')
        finally:
            self.busy.discard(uid)

    async def message(self, chat, uid, update_id, text, sender, session):
        text = text.strip()
        command, _, argument = text.partition(' ')
        command = command.split('@')[0].lower()
        if command == '/start' and argument:
            code = argument
            await self.api.request('POST', '/telegram/consume-link', body={
                'code': code, 'telegram_user_id': uid, 'chat_id': chat, 'username': sender.get('username')})
            session.flow = None
            session.refs.clear()
            await self.sync_link(uid, session)
            await self.tg.send(chat, 'Аккаунт связан с сайтом. Заявки, обучение и уведомления теперь общие.')
            await self.menu(chat, uid)
        elif command in ('/start', '/menu', '/help'):
            session.flow = None
            await self.menu(chat, uid)
        elif command == '/stop':
            await self.api.request('DELETE', '/telegram/link', uid)
            self.sessions.pop(uid, None)
            await self.tg.send(chat, 'Telegram отключён. Уведомления и доступ к данным остановлены. Для подключения создайте новую ссылку на сайте.')
        elif command == '/cancel':
            session.flow = None
            session.refs.clear()
            await self.tg.send(chat, 'Ввод отменён. /menu — открыть меню.')
        elif command in ('/profile', '/requests', '/courses', '/calendar', '/notifications'):
            names = {'/requests': 'requests:mine:0', '/courses': 'courses:0', '/notifications': 'notifications:0'}
            session.flow = None
            await self.callback(chat, uid, update_id, names.get(command, command[1:]), session)
        elif command == '/ask':
            if not argument.strip():
                await self.tg.send(chat, 'Напишите вопрос после /ask, например: /ask Как оформить отпуск?')
            else:
                await self.ask(chat, uid, argument, session)
        elif text.startswith('/'):
            await self.tg.send(chat, 'Неизвестная команда. /menu — все разделы, /ask — вопрос Jana.')
        elif session.flow:
            await self.flow_text(chat, uid, update_id, text, session)
        elif text:
            await self.ask(chat, uid, text, session)
        else:
            await self.tg.send(chat, 'Пока принимаю текстовые сообщения. /menu — открыть меню.')

    async def confirm(self, chat, uid, update_id, session, title, method, path, body=None):
        action = {'kind': 'confirm', 'method': method, 'path': path, 'body': body,
                  'key': mutation_key(uid, update_id, f'{method}:{path}')}
        token = session.ref(action)
        await self.tg.send(chat, title + '\nПодтвердить?', keyboard([[('Подтвердить', f'ref:{token}')], [('Отмена', 'cancel')]]))
        session.flow = None

    async def flow_text(self, chat, uid, update_id, text, session):
        flow = session.flow
        if flow['step'] == 'leave_dates':
            try:
                dates = text.split()
                if len(dates) != 2:
                    raise ValueError()
                start, end = map(parse_date, dates)
                if end < start:
                    raise ValueError()
            except ValueError:
                await self.tg.send(chat, 'Введите две даты начала и конца: 10.11.2026 12.11.2026. /cancel — отмена.')
                return
            flow.update(step='comment', body={'request_type': 'leave', 'start_date': start.isoformat(), 'end_date': end.isoformat()})
            await self.tg.send(chat, 'Комментарий к отпуску (или «-», если не нужен):')
        elif flow['step'] == 'advance_amount':
            try:
                amount = Decimal(text.replace(' ', '').replace(',', '.'))
                if not amount.is_finite() or amount <= 0 or amount > 1_000_000 or amount != amount.quantize(Decimal('.01')):
                    raise InvalidOperation()
            except InvalidOperation:
                await self.tg.send(chat, 'Введите сумму в тенге, например 50000, не больше 1000000 и не более двух знаков после запятой.')
                return
            flow.update(step='comment', body={'request_type': 'advance', 'amount': float(amount)})
            await self.tg.send(chat, 'Комментарий к авансу (или «-», если не нужен):')
        elif flow['step'] == 'comment':
            if len(text) > 2000:
                await self.tg.send(chat, 'Комментарий должен быть не длиннее 2000 символов.')
                return
            body = {**flow['body'], 'comment': '' if text == '-' else text}
            await self.confirm(chat, uid, update_id, session, short_request(body) + f"\nКомментарий: {body['comment'] or '—'}", 'POST', '/requests', body)
        elif flow['step'] == 'reject_reason':
            if not text or len(text) > 2000:
                await self.tg.send(chat, 'Введите причину отказа, не более 2000 символов.')
                return
            await self.confirm(chat, uid, update_id, session, f'Отклонить заявку?\nПричина: {text}', 'PATCH',
                               f"/requests/{flow['request_id']}/review", {'status': 'rejected', 'reviewer_comment': text})
        elif flow['step'] == 'ticket':
            if len(text) < 3 or len(text) > 2000:
                await self.tg.send(chat, 'Вопрос должен содержать от 3 до 2000 символов.')
                return
            await self.confirm(chat, uid, update_id, session, f'Передать вопрос сотрудникам HR?\n{text}\nПодтверждая, вы соглашаетесь передать этот текст в HR.',
                               'POST', '/workspace/tickets', {'id': mutation_key(uid, update_id, 'ticket'), 'question': text, 'context': '', 'consent': True})

    async def ask(self, chat, uid, question, session):
        if not 3 <= len(question) <= 2000:
            await self.tg.send(chat, 'Введите вопрос длиной от 3 до 2000 символов.')
            return
        # Verify account before a potentially long model request and acknowledge wait.
        initial_link = await self.sync_link(uid, session)
        await self.tg.send(chat, 'Jana ищет ответ в базе знаний. Это может занять несколько минут.')
        answer = await self.api.request('POST', '/ai/ask', uid, body={'question': question})
        if await self.sync_link(uid, session) != initial_link:
            await self.tg.send(chat, 'Подключён другой аккаунт. Задайте вопрос заново через /menu.')
            return
        rows = []
        for index, source in enumerate(answer.get('sources', []), 1):
            token = session.ref({'kind': 'source', 'id': source['id'], 'version': source.get('version')})
            rows.append([(f"Источник {index}: {source['title'][:45]}", f'ref:{token}')])
        rows.append([('Задать вопрос HR', 'new:ticket')])
        await self.tg.send(chat, answer['answer'], keyboard(rows))

    async def request_card(self, chat, uid, rid):
        row = await self.api.request('GET', f'/requests/{rid}', uid)
        profile = await self.api.request('GET', '/profile', uid)
        rows = []
        if row.get('can_review'):
            rows.append([('Согласовать', f'approve:{rid}'), ('Отклонить', f'reject:{rid}')])
        if row.get('employee_id') == profile.get('id') and row.get('status') in ('pending', 'pending_hr', 'pending_director'):
            rows.append([('Отозвать заявку', f'withdraw:{rid}')])
        if row.get('status') == 'approved' and row.get('request_type') == 'leave':
            rows.append([('Скачать .ics', f'ics:{rid}')])
        rows.append([('История', f'history:{rid}'), ('Обновить', f'request:{rid}')])
        extra = f"\nКомментарий: {row.get('comment') or '—'}\nОтвет: {row.get('reviewer_comment') or '—'}"
        await self.tg.send(chat, short_request(row) + extra + f'\nID: {rid}', keyboard(rows))

    async def course_card(self, chat, uid, cid, session):
        course = await self.api.request('GET', f'/academy/courses/{cid}', uid)
        assignment = course.get('assignment') or {}
        rows = []
        for lesson in course.get('lessons') or []:
            token = session.ref({'kind': 'lesson', 'course_id': cid, 'lesson_id': lesson['id']})
            done = ' ✓' if lesson['id'] in assignment.get('completed_lesson_ids', []) else ''
            rows.append([(lesson['title'][:50] + done, f'ref:{token}')])
        if not course.get('lessons'):
            rows.append([('Читать материал', f'material:{cid}')])
        if assignment:
            rows.append([('Пройти тест', f'quiz:{cid}')])
        await self.tg.send(chat, f"{course['title']}\n{course.get('description', '')}\nПрогресс: {assignment.get('progress_percent', 0)}% · Результат: {assignment.get('score_percent') or 0}%", keyboard(rows))

    async def quiz_question(self, chat, session, quiz):
        index = len(quiz['answers'])
        if index == len(quiz['questions']):
            token = session.ref({'kind': 'confirm', 'method': 'POST', 'path': f"/academy/courses/{quiz['course_id']}/complete",
                                 'body': {'answers': quiz['answers']}, 'key': quiz['key']})
            await self.tg.send(chat, 'Ответы заполнены. Отправить тест на проверку?', keyboard([[('Отправить тест', f'ref:{token}')], [('Отмена', 'cancel')]]))
            return
        question = quiz['questions'][index]
        rows = []
        for option, title in enumerate(question['options']):
            token = session.ref({'kind': 'quiz_option', 'quiz': quiz, 'index': index, 'option': option})
            rows.append([(f'{option + 1}. {str(title)[:55]}', f'ref:{token}')])
        text = f"Вопрос {index + 1}/{len(quiz['questions'])}\n{question['prompt']}\n" + '\n'.join(f'{i + 1}. {v}' for i, v in enumerate(question['options']))
        await self.tg.send(chat, text, keyboard(rows))

    async def use_ref(self, chat, uid, update_id, token, session):
        value = session.lookup(token)
        if value is None:
            await self.tg.send(chat, 'Кнопка устарела или уже использована. Откройте нужный раздел через /menu.')
            return
        kind = value['kind']
        if kind == 'confirm':
            result = await self.api.request(value['method'], value['path'], uid, body=value.get('body'), key=value['key'])
            text = 'Сохранено. Изменения доступны и на сайте.'
            if result and 'request_type' in result:
                text += '\n' + short_request(result)
            elif result and 'score_percent' in result:
                text += f"\nРезультат: {result['score_percent']}% · {'Пройдено' if result.get('status') == 'completed' else 'Повторите материал и попробуйте снова'}"
            await self.tg.send(chat, text)
            session.refs.pop(token, None)
        elif kind == 'source':
            source = await self.api.request('GET', f"/ai/sources/{value['id']}", uid,
                                             params={'version': value['version']} if value.get('version') else None)
            text = f"{source['title']}\n\n{source['content']}\n\nИсточник: {source.get('source_title', '')}"
            if source.get('source_url'):
                text += '\n' + source['source_url']
            await self.tg.send(chat, text)
        elif kind == 'lesson':
            course = await self.api.request('GET', f"/academy/courses/{value['course_id']}", uid)
            lesson = next((x for x in course.get('lessons', []) if x['id'] == value['lesson_id']), None)
            if lesson is None:
                raise RemoteError('Portal', 404)
            mark = session.ref({'kind': 'confirm', 'method': 'POST',
                               'path': f"/workspace/courses/{value['course_id']}/lessons/{quote(lesson['id'], safe='')}/complete",
                               'body': None, 'key': mutation_key(uid, update_id, 'lesson')})
            await self.tg.send(chat, f"{lesson['title']}\n\n{lesson['material_markdown']}", keyboard([[('Я изучил(а) урок', f'ref:{mark}')]]))
        elif kind == 'quiz_option':
            quiz, index = value['quiz'], value['index']
            if len(quiz['answers']) != index:
                await self.tg.send(chat, 'Ответ уже выбран. Продолжите тест с последнего вопроса.')
                return
            quiz['answers'][quiz['questions'][index]['id']] = value['option']
            await self.quiz_question(chat, session, quiz)

    async def callback(self, chat, uid, update_id, data, session):
        parts = data.split(':')
        action = parts[0]
        if action == 'ref' and len(parts) == 2:
            await self.use_ref(chat, uid, update_id, parts[1], session)
        elif action == 'menu':
            await self.menu(chat, uid)
        elif action == 'cancel':
            session.flow = None
            session.refs.clear()
            await self.tg.send(chat, 'Отменено. /menu — открыть меню.')
        elif action == 'ask':
            session.flow = None
            await self.tg.send(chat, 'Напишите вопрос о правилах и процессах JanaPost. Jana ответит по базе знаний и покажет источники.')
        elif action == 'profile':
            row = await self.api.request('GET', '/profile', uid)
            await self.tg.send(chat, f"{row.get('full_name', '')}\n{row.get('job_title') or '—'} · {row.get('department') or '—'}\nРоль: {ROLE.get(row.get('role'), '—')}\nРуководитель: {row.get('manager_name') or '—'}\nОстаток отпуска: {row.get('vacation_days_remaining', '—')} дн.")
        elif action == 'new' and len(parts) == 2:
            await self.api.request('GET', '/telegram/status', uid)
            if parts[1] in ('leave', 'advance'):
                routing = await self.api.request('GET', '/requests/routing', uid)
                if not routing.get('can_submit'):
                    await self.tg.send(chat, routing.get('message') or 'Маршрут согласования пока не настроен. Обратитесь к HR.')
                    return
                session.flow = {'step': 'leave_dates' if parts[1] == 'leave' else 'advance_amount'}
                await self.tg.send(chat, 'Введите даты отпуска: 10.11.2026 12.11.2026.' if parts[1] == 'leave' else 'Введите сумму аванса в тенге. /cancel — отмена.')
            elif parts[1] == 'ticket':
                session.flow = {'step': 'ticket'}
                await self.tg.send(chat, 'Напишите вопрос для HR. Перед отправкой будет подтверждение. /cancel — отмена.')
        elif action == 'requests' and len(parts) == 3 and parts[1] in ('mine', 'review'):
            offset = max(0, int(parts[2]))
            rows = await self.api.request('GET', '/requests', uid, params={'scope': parts[1], 'limit': PAGE, 'offset': offset})
            buttons = [[(short_request(row).replace('\n', ' · ')[:60], f"request:{row['id']}")] for row in rows]
            if offset:
                buttons.append([('Назад', f'requests:{parts[1]}:{max(0, offset - PAGE)}')])
            if len(rows) == PAGE:
                buttons.append([('Далее', f'requests:{parts[1]}:{offset + PAGE}')])
            await self.tg.send(chat, 'Выберите заявку:' if rows else 'Заявок нет.', keyboard(buttons))
        elif action == 'request' and len(parts) == 2:
            await self.request_card(chat, uid, parts[1])
        elif action in ('approve', 'reject', 'withdraw') and len(parts) == 2:
            row = await self.api.request('GET', f'/requests/{parts[1]}', uid)
            if action == 'reject':
                session.flow = {'step': 'reject_reason', 'request_id': parts[1]}
                await self.tg.send(chat, short_request(row) + '\nВведите причину отказа:')
            else:
                path = f"/requests/{parts[1]}/{'review' if action == 'approve' else 'cancel'}"
                await self.confirm(chat, uid, update_id, session, ('Согласовать' if action == 'approve' else 'Отозвать') + '\n' + short_request(row),
                                   'PATCH' if action == 'approve' else 'POST', path, {'status': 'approved'} if action == 'approve' else None)
        elif action == 'history' and len(parts) == 2:
            rows = await self.api.request('GET', f'/requests/{parts[1]}/history', uid)
            await self.tg.send(chat, '\n\n'.join(f"{x.get('created_at', '')[:16]} · {STATUS.get(x.get('to_status'), x.get('event_type'))}\n{x.get('comment') or ''}" for x in rows) or 'История пуста.')
        elif action in ('calendar', 'ics'):
            path = f'/requests/{parts[1]}/calendar.ics' if action == 'ics' and len(parts) == 2 else '/requests/calendar.ics'
            content = await self.api.request('GET', path, uid, binary=True)
            await self.tg.call('sendDocument', {'chat_id': chat, 'caption': 'Импортируйте .ics в Google Calendar. Это снимок согласованных отпусков, без автосинхронизации.'}, document=content)
        elif action == 'courses':
            offset = max(0, int(parts[1])) if len(parts) == 2 else 0
            all_rows = await self.api.request('GET', '/academy/my-courses', uid)
            rows = all_rows[offset:offset + PAGE]
            buttons = [[(f"{(r.get('course') or {}).get('title', 'Курс')[:45]} · {r.get('progress_percent', 0)}%", f"course:{r['course_id']}")] for r in rows]
            if offset:
                buttons.append([('Назад', f'courses:{max(0, offset - PAGE)}')])
            if len(all_rows) > offset + PAGE:
                buttons.append([('Далее', f'courses:{offset + PAGE}')])
            await self.tg.send(chat, 'Ваши назначенные курсы:' if rows else 'Назначенных курсов пока нет.', keyboard(buttons))
        elif action == 'course' and len(parts) == 2:
            await self.course_card(chat, uid, parts[1], session)
        elif action in ('material', 'quiz') and len(parts) == 2:
            course = await self.api.request('GET', f'/academy/courses/{parts[1]}', uid)
            if action == 'material':
                await self.tg.send(chat, course.get('material_markdown') or 'Материал не добавлен.')
                if course.get('assignment'):
                    await self.confirm(chat, uid, update_id, session, 'Отметить материал изученным?', 'PATCH', f'/academy/courses/{parts[1]}/progress', {'progress_percent': 99})
            elif course.get('quiz'):
                await self.quiz_question(chat, session, {'course_id': parts[1], 'questions': course['quiz'], 'answers': {},
                                                        'key': mutation_key(uid, update_id, 'quiz')})
        elif action == 'notifications':
            offset = max(0, int(parts[1])) if len(parts) == 2 else 0
            rows = await self.api.request('GET', '/notifications', uid, params={'limit': PAGE, 'offset': offset})
            for row in rows:
                buttons = [[('Прочитано', f"read:{row['id']}")]]
                if row.get('request_id'):
                    buttons.append([('Заявка', f"request:{row['request_id']}")])
                if row.get('course_id'):
                    buttons.append([('Курс', f"course:{row['course_id']}")])
                await self.tg.send(chat, f"{row['title']}\n{row['body']}", keyboard(buttons))
            await self.tg.send(chat, 'Уведомления показаны.' if rows else 'Уведомлений нет.', keyboard([[('Далее', f'notifications:{offset + PAGE}')]]) if len(rows) == PAGE else None)
        elif action == 'read' and len(parts) == 2:
            await self.api.request('POST', f'/notifications/{parts[1]}/read', uid, key=mutation_key(uid, update_id, 'read'))
            await self.tg.send(chat, 'Прочитано. Статус обновлён и на сайте.')
        elif action == 'tickets':
            rows = await self.api.request('GET', '/workspace/tickets', uid, params={'limit': 10})
            buttons = [[(row['question'][:55], f"ticket:{row['id']}")] for row in rows]
            buttons.append([('Новое обращение', 'new:ticket')])
            await self.tg.send(chat, 'Последние обращения в HR:', keyboard(buttons))
        elif action == 'ticket' and len(parts) == 2:
            row = await self.api.request('GET', f'/workspace/tickets/{parts[1]}', uid)
            await self.tg.send(chat, f"Вопрос: {row['question']}\nОтвет HR: {row.get('answer') or 'Ожидает ответа'}")
        elif action == 'team':
            rows = await self.api.request('GET', '/team', uid)
            await self.tg.send(chat, '\n'.join(f"{row['full_name']} · {row.get('job_title') or '—'}" for row in rows) or 'Команда пока не назначена.')
        else:
            await self.tg.send(chat, 'Эта кнопка больше не доступна. Откройте /menu.')
