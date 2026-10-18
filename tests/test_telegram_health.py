import asyncio
from types import SimpleNamespace

import pytest

from app.telegram import worker
from app.telegram.client import RemoteError


@pytest.mark.parametrize("status", [401, 409, 503])
def test_failed_poll_does_not_report_healthy(tmp_path, monkeypatch, status):
    heartbeat = tmp_path / "heartbeat"
    heartbeat.write_text("old-process")
    monkeypatch.setattr(worker, "HEARTBEAT", heartbeat)

    async def scenario():
        async def initialize():
            assert not heartbeat.exists()

        async def call(*args, **kwargs):
            raise RemoteError("Telegram", status)

        async def stop_after_failure(*args):
            raise asyncio.CancelledError()

        poller = worker.Poller(None, None, SimpleNamespace(call=call))
        monkeypatch.setattr(poller, "initialize", initialize)
        monkeypatch.setattr(worker.asyncio, "sleep", stop_after_failure)
        with pytest.raises(asyncio.CancelledError):
            await poller.run()
        assert not heartbeat.exists()

    asyncio.run(scenario())


def test_successful_poll_updates_health_but_failed_retry_does_not(
    tmp_path, monkeypatch
):
    heartbeat = tmp_path / "heartbeat"
    monkeypatch.setattr(worker, "HEARTBEAT", heartbeat)
    monkeypatch.setattr(worker.time, "time", lambda: 1234567890.0)

    async def scenario():
        calls = 0

        async def initialize():
            pass

        async def call(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                assert not heartbeat.exists()
                return []
            assert heartbeat.read_text() == "1234567890.0"
            monkeypatch.setattr(worker.time, "time", lambda: 1234567990.0)
            raise RemoteError("Telegram", 503)

        async def stop_after_failure(*args):
            raise asyncio.CancelledError()

        poller = worker.Poller(None, None, SimpleNamespace(call=call))
        monkeypatch.setattr(poller, "initialize", initialize)
        monkeypatch.setattr(worker.asyncio, "sleep", stop_after_failure)
        with pytest.raises(asyncio.CancelledError):
            await poller.run()
        assert heartbeat.read_text() == "1234567890.0"

    asyncio.run(scenario())
