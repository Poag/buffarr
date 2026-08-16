"""Periodic scheduler for the unmonitor feature."""

import asyncio
import logging

from core.config import CONFIG
from services.job_queue import JobQueue

log = logging.getLogger("scheduler")


def get_enabled_apps() -> list:
    apps = []
    if CONFIG.ENABLE_RADARR:
        apps.append("radarr")
    if CONFIG.ENABLE_SONARR:
        apps.append("sonarr")
    return apps


async def run(queue: JobQueue) -> None:
    log.info("Scheduler started (every %d minutes)", CONFIG.SLEEP_MINUTES)
    while True:
        for app in get_enabled_apps():
            queue.add_job(app, triggered_by="scheduler")
        log.debug("Scheduler sleeping for %d minutes...", CONFIG.SLEEP_MINUTES)
        await asyncio.sleep(CONFIG.SLEEP_MINUTES * 60)
