import asyncio
import logging

import aiohttp

from core.config import CONFIG
from services import prefetch_service, scheduler, webhook
from services.job_queue import JobQueue
from services.scheduler import get_enabled_apps

log = logging.getLogger("main")


async def _report_connection(session: aiohttp.ClientSession, name: str, base_url: str, api_key: str) -> None:
    """One-off startup ping, purely to report reachability. Not a
    precondition for anything -- unmonitor's scheduled jobs retry
    independently and don't depend on this succeeding."""
    try:
        async with session.get(
            f"{base_url}/api", headers={"X-Api-Key": api_key}, timeout=aiohttp.ClientTimeout(total=10)
        ) as resp:
            resp.raise_for_status()
        log.info("Connected to %s at %s", name, base_url)
    except Exception as e:
        log.warning(
            "Could not reach %s at %s: %s (will retry on the next scheduled run)", name, base_url, e
        )


async def _report_unmonitor_connections(session: aiohttp.ClientSession) -> None:
    # prefetch_service reports its own Sonarr connection when enabled; avoid
    # a duplicate probe here in that case.
    if CONFIG.ENABLE_SONARR and CONFIG.SONARR_URL and CONFIG.SONARR_API_KEY and not CONFIG.ENABLE_PREFETCH:
        await _report_connection(session, "Sonarr", CONFIG.SONARR_URL, CONFIG.SONARR_API_KEY)
    if CONFIG.ENABLE_RADARR and CONFIG.RADARR_URL and CONFIG.RADARR_API_KEY:
        await _report_connection(session, "Radarr", CONFIG.RADARR_URL, CONFIG.RADARR_API_KEY)


async def async_main() -> None:
    log.info("buffarr starting")

    enabled_apps = get_enabled_apps()
    log.info("unmonitor apps enabled: %s", enabled_apps or "none")
    log.info("prefetch enabled: %s", CONFIG.ENABLE_PREFETCH)

    async with aiohttp.ClientSession() as session:
        await _report_unmonitor_connections(session)

        queue = JobQueue()

        tasks = [
            asyncio.create_task(queue.run(session), name="job_queue"),
            asyncio.create_task(scheduler.run(queue), name="scheduler"),
            asyncio.create_task(webhook.run(queue), name="webhook"),
        ]

        if CONFIG.ENABLE_PREFETCH:
            tasks.append(asyncio.create_task(prefetch_service.run(session), name="prefetch"))

        await asyncio.gather(*tasks)
