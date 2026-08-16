"""Plex backend.

Plex's `/status/sessions` REST endpoint does not include `playQueueID`, but
the server pushes `PlaySessionStateNotification` events over a websocket for
every active session -- that's where we learn the queue ID for a session
(needed for the optional queue-append feature), regardless of client (direct
play or transcode).
"""

import asyncio
import json
import logging

import aiohttp

from prefetch.mediaserver.base import Client as BaseClient
from prefetch.mediaserver.base import EpisodeRef, NowPlaying, Queue, Series, User

log = logging.getLogger("media_server.plex")


class Client(BaseClient, Queue):
    def __init__(self, url: str, token: str, session: aiohttp.ClientSession):
        self.url = url.rstrip("/")
        self.token = token
        self.session = session
        self._headers = {"X-Plex-Token": token, "Accept": "application/json"}
        self._machine_id = None
        self._play_queue_cache: dict = {}

    def _notifications_url(self) -> str:
        scheme = "wss" if self.url.startswith("https") else "ws"
        rest = self.url.split("://", 1)[1]
        return f"{scheme}://{rest}/:/websockets/notifications?X-Plex-Token={self.token}"

    async def _get(self, path: str):
        url = f"{self.url}/{path}"
        async with self.session.get(url, headers=self._headers) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def _tvdb(self, key: str):
        try:
            data = await self._get(key.lstrip("/"))
        except Exception:
            return None
        metas = (data.get("MediaContainer") or {}).get("Metadata") or []
        if not metas:
            return None
        for g in metas[0].get("Guid", []):
            uri = g.get("id", "")
            if "://" not in uri:
                continue
            provider, ident = uri.split("://", 1)
            if provider == "tvdb":
                try:
                    return int(ident)
                except ValueError:
                    return None
        return None

    async def probe(self) -> None:
        await self._get("status/sessions")

    async def sessions(self) -> list:
        data = await self._get("status/sessions")
        metas = (data.get("MediaContainer") or {}).get("Metadata") or []
        return [m for m in metas if m.get("type") == "episode"]

    async def extract(self, session: dict) -> NowPlaying:
        episode = session["index"]
        season = session["parentIndex"]
        series = None
        tvdb_id = await self._tvdb(session["grandparentKey"])
        if tvdb_id is not None:
            series = Series.tvdb(tvdb_id)
        else:
            series = Series.title(session["grandparentTitle"])

        user_json = session.get("User") or {}
        user = User(id=user_json["id"], name=user_json["title"])
        library = session.get("librarySectionTitle")

        # Plex always exposes a top-level `sessionKey` in /status/sessions
        # metadata; `Session.id` is only populated for some session types
        # (typically those started via a transcoding decision). We key on
        # the always-present sessionKey so every active session is
        # trackable for the queue-append path.
        session_id = session.get("sessionKey")

        return NowPlaying(
            series=series,
            episode=episode,
            season=season,
            user=user,
            library=library,
            session_id=session_id,
        )

    async def run(self) -> None:
        delay = 1
        while True:
            try:
                await self._run_notifications()
                log.debug("plex notifications stream ended; reconnecting")
                delay = 1
            except Exception as e:
                log.warning("plex notifications stream error: %s", e)
                delay = min(delay * 2, 30)
            await asyncio.sleep(delay)

    async def _run_notifications(self) -> None:
        url = self._notifications_url()
        async with self.session.ws_connect(url) as ws:
            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    try:
                        data = json.loads(msg.data)
                    except json.JSONDecodeError:
                        continue
                    self._update_play_queue_cache(data)
                elif msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                    break

    def _update_play_queue_cache(self, data: dict) -> None:
        notifications = ((data.get("NotificationContainer") or {}).get("PlaySessionStateNotification")) or []
        for n in notifications:
            session_key = n.get("sessionKey")
            if session_key is None:
                continue
            session_key = str(session_key)
            state = n.get("state", "")
            if state == "stopped":
                self._play_queue_cache.pop(session_key, None)
                continue
            pqid = n.get("playQueueID")
            if pqid is not None:
                self._play_queue_cache[session_key] = pqid

    async def _machine_identifier(self) -> str:
        if self._machine_id is None:
            data = await self._get("identity")
            self._machine_id = (data.get("MediaContainer") or {}).get("machineIdentifier")
            if not self._machine_id:
                raise ValueError("missing machineIdentifier in /identity")
        return self._machine_id

    async def _list_series_episodes(self, series_key: str) -> dict:
        path = f"{series_key.lstrip('/')}/allLeaves"
        data = await self._get(path)
        out = {}
        for item in (data.get("MediaContainer") or {}).get("Metadata") or []:
            s = item.get("parentIndex")
            e = item.get("index")
            key = item.get("ratingKey")
            if s is not None and e is not None and key is not None:
                out[EpisodeRef(s, e)] = key
        return out

    async def _play_queue_rating_keys(self, play_queue_id) -> set:
        data = await self._get(f"playQueues/{play_queue_id}")
        metas = (data.get("MediaContainer") or {}).get("Metadata") or []
        return {m["ratingKey"] for m in metas if m.get("ratingKey")}

    async def append(self, np: NowPlaying, episodes: list) -> set:
        if not np.session_id:
            raise ValueError("session_id missing")

        data = await self._get("status/sessions")
        metas = (data.get("MediaContainer") or {}).get("Metadata") or []
        session = next((m for m in metas if m.get("sessionKey") == np.session_id), None)
        if session is None:
            raise ValueError(f"session {np.session_id} no longer exists")

        play_queue_id = self._play_queue_cache.get(np.session_id)
        if play_queue_id is None:
            log.debug(
                "playQueueID not yet observed via websocket for session %s; will retry next poll",
                np.session_id,
            )
            return set()

        series_key = session.get("grandparentKey")
        if not series_key:
            raise ValueError("session has no grandparentKey")

        machine_id = await self._machine_identifier()
        episode_map = await self._list_series_episodes(series_key)
        existing = await self._play_queue_rating_keys(play_queue_id)

        success = set()
        to_put = []
        for ep in episodes:
            rk = episode_map.get(ep)
            if rk is None:
                log.debug("s%02de%02d not yet in library; stop", ep.season, ep.episode)
                break
            if rk in existing:
                log.debug("s%02de%02d already in queue", ep.season, ep.episode)
                success.add(ep)
            else:
                to_put.append((ep, rk))

        for ep, rk in to_put:
            uri = f"server://{machine_id}/com.plexapp.plugins.library/library/metadata/{rk}"
            url = f"{self.url}/playQueues/{play_queue_id}"
            async with self.session.put(url, headers=self._headers, params={"uri": uri}) as resp:
                resp.raise_for_status()
            log.info("appended %s to play queue", ep)
            success.add(ep)

        return success
