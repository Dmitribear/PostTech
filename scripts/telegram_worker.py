"""Run one Telegram long-polling worker after the bot token is configured."""
import asyncio
import logging
import ssl
import sys
from pathlib import Path

from dotenv import load_dotenv
import httpx

from app.telegram.bot import Bot
from app.telegram.client import BotConfig, PortalClient, RemoteError, TelegramClient
from app.telegram.worker import Poller, notification_loop


async def run(config):
    if sys.platform == 'win32':
        import truststore
        tls = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    else:
        tls = ssl.create_default_context()
    async with httpx.AsyncClient(verify=tls, follow_redirects=False, limits=httpx.Limits(max_connections=40)) as http:
        portal, telegram = PortalClient(config, http), TelegramClient(config, http)
        bot = Bot(portal, telegram, config.portal_url)
        poller = Poller(bot, portal, telegram)
        # A failed background delivery loop must fail the process so Docker can
        # restart it; otherwise a healthy poller would conceal dead notifications.
        async with asyncio.TaskGroup() as group:
            group.create_task(notification_loop(portal, telegram))
            group.create_task(poller.run())


def main():
    # This worker never loads unrelated OpenAI/Supabase secrets from the main .env.
    load_dotenv(Path(__file__).resolve().parents[1] / '.local' / 'telegram.env', override=False)
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    # httpx request INFO records include the Telegram token in the URL.
    logging.getLogger('httpx').setLevel(logging.CRITICAL)
    logging.getLogger('httpcore').setLevel(logging.CRITICAL)
    try:
        config = BotConfig.from_env()
        asyncio.run(run(config))
    except KeyboardInterrupt:
        pass
    except Exception:
        logging.error('Telegram worker could not start. Check bot configuration, connectivity and migrations; no secrets were logged.')
        raise SystemExit(2)


if __name__ == '__main__':
    main()
