"""Jellyfin/Emby backend. Both forks share the same REST API and only differ
in the auth header."""

import logging
from typing import Optional

import aiohttp

from prefetch.mediaserver.base import Client as BaseClient
from prefetch.mediaserver.base import EpisodeRef, NowPlaying, Queue, Series, User

log = logging.getLogger("media_server.embyfin")

JELLYFIN = "jellyfin"
EMBY = "emby"


class Client(BaseClient, Queue):
    def __init__(self, base_url: str, api_key: str, fork: str, session: aiohttp.ClientSession):
        self.base_url = base_url.rstrip("/")
        self.fork = fork
        self.session = session
        if fork == JELLYFIN:
            self._headers = {"Authorization": f'MediaBrowser Token="{api_key}"'}
        elif fork == EMBY:
            self._headers = {"X-Emby-Token": api_key}
        else:
            raise ValueError(f"unknown fork: {fork}")
        self._headers["Accept"] = "application/json"

    async def _get(self, path: str, params: Optional[dict] = None):
        url = f"{self.base_url}/{path}"
        async with self.session.get(url, headers=self._headers, params=params) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def _item(self, user_id: str, item_id: str):
        return await self._get(f"Users/{user_id}/Items/{item_id}")

    async def _virtual_folders(self):
        return await self._get("Library/VirtualFolders")

    async def probe(self) -> None:
        await self._get("System/Endpoint")

    async def sessions(self) -> list:
        raw = await self._get("Sessions")
        valid = []
        for s in raw:
            item = s.get("NowPlayingItem")
            if (
                isinstance(s.get("UserId"), str)
                and isinstance(s.get("UserName"), str)
                and isinstance(item, dict)
                and isinstance(item.get("SeriesId"), str)
                and isinstance(item.get("SeasonId"), str)
                and isinstance(item.get("IndexNumber"), int)
                and isinstance(item.get("Path"), str)
            ):
                valid.append(s)
            else:
                log.debug("ignoring malformed session entry: %s", s)
        return valid

    async def extract(self, session: dict) -> NowPlaying:
        item = session["NowPlayingItem"]
        user_id = session["UserId"]
        series_id = item["SeriesId"]
        season_id = item["SeasonId"]

        series_item = await self._item(user_id, series_id)
        season_item = await self._item(user_id, season_id)
        season_num = season_item["IndexNumber"]

        provider_ids = series_item.get("ProviderIds") or {}
        tvdb = provider_ids.get("Tvdb")
        series = Series.tvdb(int(tvdb)) if tvdb else Series.title(series_item["Name"])

        item_path = item["Path"]
        library = None
        for folder in await self._virtual_folders():
            if any(item_path.startswith(loc) for loc in folder.get("Locations", [])):
                library = folder.get("Name")
                break

        return NowPlaying(
            series=series,
            episode=item["IndexNumber"],
            season=season_num,
            user=User(id=user_id, name=session["UserName"]),
            library=library,
            session_id=session.get("Id"),
        )

    async def _list_series_episodes(self, series_id: str, user_id: str) -> dict:
        url = f"{self.base_url}/Shows/{series_id}/Episodes"
        params = {"userId": user_id, "fields": "ParentIndexNumber,IndexNumber"}
        async with self.session.get(url, headers=self._headers, params=params) as resp:
            resp.raise_for_status()
            data = await resp.json()

        out = {}
        for item in data.get("Items", []):
            season = item.get("ParentIndexNumber")
            episode = item.get("IndexNumber")
            item_id = item.get("Id")
            if season is not None and episode is not None and item_id is not None:
                out[EpisodeRef(season, episode)] = item_id
        return out

    async def append(self, np: NowPlaying, episodes: list) -> set:
        if not np.session_id:
            raise ValueError("session_id missing")

        raw_sessions = await self._get("Sessions")
        session = next((s for s in raw_sessions if s.get("Id") == np.session_id), None)
        if session is None:
            raise ValueError(f"session {np.session_id} no longer exists")

        series_id = (session.get("NowPlayingItem") or {}).get("SeriesId")
        user_id = session.get("UserId")
        if not series_id:
            raise ValueError("session has no SeriesId")
        if not user_id:
            raise ValueError("session has no UserId")

        existing = {
            i.get("Id") for i in (session.get("NowPlayingQueue") or []) if i.get("Id")
        }

        episode_map = await self._list_series_episodes(series_id, user_id)

        success = set()
        to_post = []
        # Episodes arrive in playback order; stop at the first gap (episode
        # not yet in the library) so we never enqueue an episode whose
        # predecessor is still missing.
        for ep in episodes:
            item_id = episode_map.get(ep)
            if item_id is None:
                log.debug("s%02de%02d not yet in library; stop", ep.season, ep.episode)
                break
            if item_id in existing:
                log.debug("s%02de%02d already in queue", ep.season, ep.episode)
                success.add(ep)
            else:
                to_post.append((ep, item_id))

        if to_post:
            item_ids = ",".join(item_id for _, item_id in to_post)
            url = f"{self.base_url}/Sessions/{np.session_id}/Playing"
            params = {"playCommand": "PlayLast", "itemIds": item_ids}
            async with self.session.post(url, headers=self._headers, params=params) as resp:
                resp.raise_for_status()
            log.info("appended %s to play queue", [str(ep) for ep, _ in to_post])
            for ep, _ in to_post:
                success.add(ep)

        return success
