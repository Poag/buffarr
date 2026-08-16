"""Wires up the prefetch feature: builds the configured media-server backend,
watches for playback sessions, and drives the Sonarr prefetch Actor."""

import asyncio
import logging

import aiohttp

from core.config import CONFIG
from prefetch.actor import Actor
from prefetch.mediaserver import jellyfin_emby, plex, tautulli
from prefetch.mediaserver.base import HasPendingFlag, libraries_filter, users_filter
from sonarr.client import Client as SonarrClient

log = logging.getLogger("prefetch_service")


def _build_media_client(session: aiohttp.ClientSession):
    server_type = CONFIG.MEDIA_SERVER_TYPE
    if server_type in (jellyfin_emby.JELLYFIN, jellyfin_emby.EMBY):
        client = jellyfin_emby.Client(
            CONFIG.MEDIA_SERVER_URL, CONFIG.MEDIA_SERVER_API_KEY, server_type, session
        )
        queue = client if CONFIG.PREFETCH_APPEND_TO_QUEUE else None
        return client, queue
    if server_type == "plex":
        client = plex.Client(CONFIG.MEDIA_SERVER_URL, CONFIG.MEDIA_SERVER_API_KEY, session)
        queue = client if CONFIG.PREFETCH_APPEND_TO_QUEUE else None
        return client, queue
    if server_type == "tautulli":
        client = tautulli.Client(CONFIG.MEDIA_SERVER_URL, CONFIG.MEDIA_SERVER_API_KEY, session)
        if CONFIG.PREFETCH_APPEND_TO_QUEUE:
            log.warning(
                "append_to_queue is not supported with Tautulli (read-only). "
                "The feature will be a no-op for this backend."
            )
        return client, None
    raise ValueError(f"unknown MEDIA_SERVER_TYPE: {server_type!r}")


async def run(session: aiohttp.ClientSession) -> None:
    if not CONFIG.ENABLE_PREFETCH:
        return

    if not (CONFIG.SONARR_URL and CONFIG.SONARR_API_KEY):
        log.error("ENABLE_PREFETCH is set but SONARR_URL/SONARR_API_KEY are missing")
        return
    if not (CONFIG.MEDIA_SERVER_URL and CONFIG.MEDIA_SERVER_API_KEY):
        log.error("ENABLE_PREFETCH is set but MEDIA_SERVER_URL/MEDIA_SERVER_API_KEY are missing")
        return

    sonarr = SonarrClient(CONFIG.SONARR_URL, CONFIG.SONARR_API_KEY, session)
    from core.retry import retry

    await retry(CONFIG.PREFETCH_CONNECTION_RETRIES, sonarr.probe)
    log.info("Connected to Sonarr at %s", CONFIG.SONARR_URL)

    media_client, queue = _build_media_client(session)
    await media_client.probe_with_retry(CONFIG.PREFETCH_CONNECTION_RETRIES)
    log.info("Connected to %s at %s", CONFIG.MEDIA_SERVER_TYPE, CONFIG.MEDIA_SERVER_URL)
    log.info("Start watching %s sessions", CONFIG.MEDIA_SERVER_TYPE)

    has_pending = HasPendingFlag()
    pending_ttl = CONFIG.PREFETCH_INTERVAL * 2 + 60

    actor = Actor(
        sonarr=sonarr,
        prefetch_num=CONFIG.PREFETCH_NUM,
        request_seasons=CONFIG.PREFETCH_REQUEST_SEASONS,
        exclude_tag_label=CONFIG.PREFETCH_EXCLUDE_TAG,
        check_aired=CONFIG.PREFETCH_CHECK_AIRED,
        queue=queue,
        has_pending=has_pending,
        pending_ttl=pending_ttl,
    )

    user_filter = users_filter(CONFIG.MEDIA_SERVER_USERS)
    library_filter = libraries_filter(CONFIG.MEDIA_SERVER_LIBRARIES)

    async def watch_sessions():
        async for np in media_client.now_playing_updates(CONFIG.PREFETCH_INTERVAL, has_pending):
            if not user_filter(np):
                continue
            if not library_filter(np):
                continue
            try:
                await actor.prefetch(np)
            except Exception as e:
                log.error("Failed to process %s: %s", np, e)

    await asyncio.gather(watch_sessions(), media_client.run())
