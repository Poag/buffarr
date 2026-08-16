"""Tautulli backend (read-only Plex proxy). Tautulli has no play-queue API,
so this backend never supports the `append_to_queue` feature."""

import logging

import aiohttp

from prefetch.mediaserver.base import Client as BaseClient
from prefetch.mediaserver.base import NowPlaying, Series, User

log = logging.getLogger("media_server.tautulli")


def _as_int(value) -> int:
    return int(value)


class Client(BaseClient):
    def __init__(self, url: str, api_key: str, session: aiohttp.ClientSession):
        self.url = url.rstrip("/")
        self.api_key = api_key
        self.session = session
        self._headers = {"Accept": "application/json"}

    async def _get(self, cmd: str):
        url = f"{self.url}/api/v2"
        params = {"apikey": self.api_key, "cmd": cmd}
        async with self.session.get(url, headers=self._headers, params=params) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def probe(self) -> None:
        await self._get("get_activity")

    async def sessions(self) -> list:
        data = await self._get("get_activity")
        response = data.get("response")
        if response is None:
            raise ValueError("Tautulli response missing `response` field")
        payload = response.get("data")
        if payload is None:
            raise ValueError("Tautulli response missing `data` field")

        raw_sessions = payload.get("sessions")
        if raw_sessions is None:
            return []

        valid = []
        for s in raw_sessions:
            try:
                _as_int(s["media_index"])
                _as_int(s["parent_media_index"])
                _as_int(s["user_id"])
                s["grandparent_title"]
                s["grandparent_guids"]
                s["media_type"]
                s["username"]
                s["library_name"]
                valid.append(s)
            except (KeyError, TypeError, ValueError) as e:
                log.warning("Skipping Tautulli session due to deserialization error: %s", e)
        return valid

    async def extract(self, session: dict) -> NowPlaying:
        if session["media_type"] != "episode":
            raise ValueError("not an episode")

        episode = _as_int(session["media_index"])
        season = _as_int(session["parent_media_index"])

        tvdb_id = None
        for uri in session["grandparent_guids"]:
            if "://" not in uri:
                continue
            provider, ident = uri.split("://", 1)
            if provider == "tvdb":
                try:
                    tvdb_id = int(ident)
                    break
                except ValueError:
                    continue

        series = Series.tvdb(tvdb_id) if tvdb_id is not None else Series.title(session["grandparent_title"])
        user = User(id=str(_as_int(session["user_id"])), name=session["username"])
        library = session["library_name"]

        return NowPlaying(
            series=series,
            episode=episode,
            season=season,
            user=user,
            library=library,
            session_id=None,
        )
