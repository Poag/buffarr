import aiohttp
from aiohttp.test_utils import TestClient, TestServer

from core.config import CONFIG
from services.job_queue import JobQueue
from services.webhook import make_app, run


async def test_access_log_disabled_for_health_polling(monkeypatch, caplog):
    """The Docker healthcheck polls /health every ~30s -- aiohttp's default
    per-request access log would flood the logs with that forever, so
    run() must disable it."""
    monkeypatch.setattr(CONFIG, "WEBHOOK_PORT", 18199)

    queue = JobQueue()
    with caplog.at_level("INFO"):
        await run(queue)
        async with aiohttp.ClientSession() as client:
            resp = await client.get("http://127.0.0.1:18199/health")
            assert resp.status == 200

    assert not any(r.name == "aiohttp.access" for r in caplog.records)


async def test_trigger_and_health_endpoints():
    queue = JobQueue()
    app = make_app(queue)
    async with TestClient(TestServer(app)) as client:
        resp = await client.get("/health")
        assert resp.status == 200
        assert (await resp.json())["status"] == "healthy"

        resp = await client.post("/trigger/sonarr")
        assert resp.status == 202
        assert (await resp.json()) == {"status": "queued", "job": "sonarr"}

        resp = await client.post("/trigger/radarr")
        assert resp.status == 202

    assert queue._queue.qsize() == 2
