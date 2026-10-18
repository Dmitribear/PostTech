"""Long polling with contiguous durable checkpoints and leased notification delivery.

Telegram confirms older updates when getUpdates is called with a higher offset.
We never advance that offset beyond unfinished jobs. While a slow AI job runs,
repeated reads of the same window admit other users without losing replay safety.
A single worker replica is required by Telegram's polling protocol.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
import tempfile
import time

from app.telegram.bot import keyboard
from app.telegram.client import RemoteError

logger = logging.getLogger(__name__)
HEARTBEAT = Path(tempfile.gettempdir()) / 'telegram-worker-heartbeat'


class Poller:
    def __init__(self, bot, portal, telegram):
        self.bot, self.api, self.tg = bot, portal, telegram
        self.offset = 0
        self.bot_id = None
        self.pending: dict[int, tuple[dict, asyncio.Task]] = {}
        self.retry_at: dict[int, float] = {}
        self.semaphore = asyncio.Semaphore(16)

    async def initialize(self):
        identity = await self.tg.call('getMe')
        self.bot_id = identity['id']
        state = await self.api.request('GET', '/telegram/worker-state', params={'bot_id': self.bot_id})
        self.offset = int(state.get('offset', 0))
        # Do not silently remove someone else's webhook or discard pending updates.
        info = await self.tg.call('getWebhookInfo')
        if info.get('url'):
            raise ValueError('Remove the existing Telegram webhook before starting the polling worker')
        await self.tg.call('setMyCommands', {'commands': [
            {'command': 'menu', 'description': 'Меню JanaМен'},
            {'command': 'ask', 'description': 'Спросить Jana'},
            {'command': 'requests', 'description': 'Мои заявки'},
            {'command': 'courses', 'description': 'Мои курсы'},
            {'command': 'calendar', 'description': 'Календарь отпусков .ics'},
            {'command': 'cancel', 'description': 'Отменить ввод'},
            {'command': 'stop', 'description': 'Отключить Telegram от аккаунта'}]})

    async def _handle(self, update):
        async with self.semaphore:
            try:
                await self.bot.handle_update(update)
            except RemoteError as exc:
                if exc.service != 'Telegram' or exc.status != 403:
                    raise

    def accept(self, updates):
        for update in sorted(updates, key=lambda item: item['update_id']):
            uid = update['update_id']
            if uid >= self.offset and uid not in self.pending:
                self.pending[uid] = (update, asyncio.create_task(self._handle(update)))

    async def checkpoint(self):
        completed = []
        for uid in sorted(self.pending):
            update, task = self.pending[uid]
            if not task.done():
                break
            if task.cancelled() or task.exception() is not None:
                if uid not in self.retry_at:
                    logger.warning('Telegram update delivery deferred; retrying safely')
                    error = None if task.cancelled() else task.exception()
                    self.retry_at[uid] = time.monotonic() + (error.retry_after if isinstance(error, RemoteError) else 5)
                elif time.monotonic() >= self.retry_at[uid]:
                    self.pending[uid] = (update, asyncio.create_task(self._handle(update)))
                    self.retry_at.pop(uid, None)
                break
            completed.append(uid)
        if completed:
            new_offset = completed[-1] + 1
            await self.api.request('PATCH', '/telegram/worker-state', body={'bot_id': self.bot_id, 'offset': new_offset})
            self.offset = new_offset
            for uid in completed:
                self.pending.pop(uid)
                self.retry_at.pop(uid, None)

    async def run(self):
        await self.initialize()
        try:
            while True:
                HEARTBEAT.write_text(str(time.time()), encoding='ascii')
                try:
                    await self.checkpoint()
                    updates = await self.tg.call('getUpdates', {
                        'offset': self.offset, 'timeout': 20, 'limit': 100,
                        'allowed_updates': ['message', 'callback_query']})
                    self.accept(updates or [])
                    # With unfinished jobs Telegram may return the same window
                    # immediately. This bound avoids a busy network loop.
                    if self.pending:
                        await asyncio.sleep(1)
                except RemoteError as exc:
                    logger.warning('Telegram polling temporarily unavailable (status=%s)', exc.status)
                    await asyncio.sleep(min(exc.retry_after, 30))
        finally:
            for _, task in self.pending.values():
                task.cancel()
            await asyncio.gather(*(task for _, task in self.pending.values()), return_exceptions=True)


async def _send_notification(row, portal, telegram):
    uid, chat = row['telegram_user_id'], row['chat_id']
    if not isinstance(uid, int) or uid <= 0 or chat != uid:
        return 'blocked'
    # Recheck identity immediately before delivery, including unlink/relink.
    current = await portal.request('GET', '/telegram/status', uid)
    if (not current.get('linked', False) or not current.get('notifications_enabled', False)
            or not row.get('link_id') or current.get('link_id') != row['link_id']):
        return 'blocked'
    buttons = []
    for field, title, command in (('request_id', 'Открыть заявку', 'request'),
                                  ('course_id', 'Открыть курс', 'course'),
                                  ('ticket_id', 'Открыть обращение', 'ticket')):
        if row.get(field):
            buttons.append([(title, f'{command}:{row[field]}')])
    await telegram.send(chat, f"{row['title']}\n{row['body']}", keyboard(buttons) if buttons else None,
                        retry_rate_limit=False)
    return 'sent'


async def deliver_notifications(portal, telegram):
    # One leased item at a time; later records never wait behind a slow send.
    rows = await portal.request('GET', '/telegram/outbox', params={'limit': 1})
    for row in rows:
        status, retry_after = 'sent', 5
        try:
            # Includes link lookup, chat lock, all chunks and network calls.
            # The database lease is 120 seconds; reserve time for acknowledgement.
            async with asyncio.timeout(85):
                status = await _send_notification(row, portal, telegram)
        except RemoteError as exc:
            status = 'blocked' if (exc.service == 'Telegram' and exc.status == 403) or (exc.service == 'Portal' and exc.status in (401, 403)) else 'retry'
            retry_after = exc.retry_after
        except TimeoutError:
            status, retry_after = 'retry', 30
        try:
            async with asyncio.timeout(15):
                await portal.request('POST', f"/telegram/outbox/{row['id']}/ack", body={
                    'lease_token': row['lease_token'], 'status': status, 'retry_after_seconds': retry_after})
        except TimeoutError:
            raise RemoteError('Portal') from None
    return len(rows)


async def notification_loop(portal, telegram):
    while True:
        delivered = 0
        try:
            delivered = await deliver_notifications(portal, telegram)
        except RemoteError as exc:
            logger.warning('Telegram notification delivery deferred (status=%s)', exc.status)
        await asyncio.sleep(0.1 if delivered else 5)
