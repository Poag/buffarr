import asyncio

import aiohttp

from services.job_queue import JobQueue


async def test_job_queue_dispatches_to_job_function(monkeypatch):
    calls = []

    async def fake_sonarr(session):
        calls.append("sonarr")

    async def fake_radarr(session):
        calls.append("radarr")

    monkeypatch.setitem(__import__("services.job_queue", fromlist=["JOB_FUNCTIONS"]).JOB_FUNCTIONS, "sonarr", fake_sonarr)
    monkeypatch.setitem(__import__("services.job_queue", fromlist=["JOB_FUNCTIONS"]).JOB_FUNCTIONS, "radarr", fake_radarr)

    queue = JobQueue()
    queue.add_job("sonarr")
    queue.add_job("radarr")

    async with aiohttp.ClientSession() as session:
        task = asyncio.create_task(queue.run(session))
        for _ in range(50):
            if len(calls) == 2:
                break
            await asyncio.sleep(0.02)
        task.cancel()

    assert set(calls) == {"sonarr", "radarr"}


def test_unknown_job_type_is_ignored():
    queue = JobQueue()
    queue.add_job("unknown")
    assert queue._queue.empty()
