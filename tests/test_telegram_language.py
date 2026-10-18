import asyncio

import httpx
import pytest
from pydantic import SecretStr

from app.telegram.client import BotConfig, PortalClient


@pytest.mark.parametrize(
    "language,expected", [("kk", "kk"), ("ru", "ru"), ("other", "ru")]
)
def test_request_language_is_isolated_and_does_not_override_auth(language, expected):
    async def scenario():
        seen = []

        def response(request):
            seen.append(request)
            return httpx.Response(200, json={"answer": "test"})

        config = BotConfig(SecretStr("test-token"), SecretStr("test-worker-secret"))
        async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as http:
            portal = PortalClient(config, http)
            await portal.request("POST", "/ai/ask", 123, language=language)
            await portal.request("GET", "/profile", 456)
        assert seen[0].headers["Accept-Language"] == expected
        assert seen[1].headers["Accept-Language"] == "ru"
        assert seen[0].headers["X-Telegram-Worker-Key"] == "test-worker-secret"
        assert seen[0].headers["X-Telegram-User-Id"] == "123"
        assert seen[1].headers["X-Telegram-User-Id"] == "456"

    asyncio.run(scenario())
