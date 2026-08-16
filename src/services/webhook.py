"""Webhook + health-check HTTP server."""

import logging

from aiohttp import web

from core.config import CONFIG
from services.job_queue import JobQueue

log = logging.getLogger("webhook_service")


def make_app(queue: JobQueue) -> web.Application:
    app = web.Application()

    async def trigger_sonarr(request):
        log.info("Sonarr trigger received via webhook.")
        queue.add_job("sonarr", triggered_by="webhook")
        return web.json_response({"status": "queued", "job": "sonarr"}, status=202)

    async def trigger_radarr(request):
        log.info("Radarr trigger received via webhook.")
        queue.add_job("radarr", triggered_by="webhook")
        return web.json_response({"status": "queued", "job": "radarr"}, status=202)

    async def health(request):
        return web.json_response({"status": "healthy", "service": "buffarr"})

    app.router.add_post("/trigger/sonarr", trigger_sonarr)
    app.router.add_post("/trigger/radarr", trigger_radarr)
    app.router.add_get("/health", health)
    return app


async def run(queue: JobQueue) -> None:
    app = make_app(queue)
    # Disable aiohttp's per-request access log -- the Docker healthcheck
    # polls /health every ~30s, which would otherwise flood the logs
    # forever. Anything worth logging (webhook triggers) is already logged
    # explicitly by the handlers above.
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", CONFIG.WEBHOOK_PORT)
    await site.start()
    log.info("Webhook server running on port %d", CONFIG.WEBHOOK_PORT)
