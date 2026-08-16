"""Async job queue for the unmonitor feature. A single background task pulls
(job_type, triggered_by) pairs and runs them serially per job type -- a lock
per job type prevents e.g. two overlapping Sonarr passes if the scheduler and
a webhook fire close together."""

import asyncio
import logging

import aiohttp

from unmonitor import radarr_job, sonarr_job

log = logging.getLogger("job_queue")

JOB_FUNCTIONS = {
    "sonarr": sonarr_job.run_job,
    "radarr": radarr_job.run_job,
}


class JobQueue:
    def __init__(self):
        self._queue: asyncio.Queue = asyncio.Queue()
        self._locks = {"sonarr": asyncio.Lock(), "radarr": asyncio.Lock()}

    def add_job(self, job_type: str, triggered_by: str = "scheduler") -> None:
        if job_type not in self._locks:
            log.warning("Unknown job type: %s", job_type)
            return
        log.debug("Queuing job: %s (triggered_by=%s)", job_type, triggered_by)
        self._queue.put_nowait((job_type, triggered_by))

    async def run(self, session: aiohttp.ClientSession) -> None:
        log.info("Job worker started and waiting for jobs...")
        while True:
            try:
                job_type, triggered_by = await self._queue.get()
                job_func = JOB_FUNCTIONS.get(job_type)
                if job_func is None:
                    log.error("Unknown job type: %s", job_type)
                    continue

                lock = self._locks[job_type]
                async with lock:
                    log.info("Starting %s job (triggered_by=%s)", job_type, triggered_by)
                    try:
                        await job_func(session)
                        log.info("Completed %s job (triggered_by=%s)", job_type, triggered_by)
                    except Exception as e:
                        log.error("Error processing %s job: %s", job_type, e, exc_info=True)
            except Exception as e:
                log.error("Unexpected error in job worker: %s", e, exc_info=True)
