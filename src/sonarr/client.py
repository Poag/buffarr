"""Async Sonarr API client used by the prefetch feature.

Series/episode/season resources are kept as plain JSON dicts (Sonarr's API is
already camelCase JSON) instead of typed structs. Includes the episode-window
sliding logic and the "monitor unannounced episodes" workaround.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

import aiohttp

log = logging.getLogger("sonarr")


def _parse_air_date(value: Optional[str]):
    if not value:
        return None
    try:
        v = value.replace("Z", "+00:00")
        dt = datetime.fromisoformat(v)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def episode_has_aired(episode: dict) -> bool:
    """No air date info is always considered aired; unparsable dates are too."""
    air = episode.get("airDateUtc") or episode.get("airDate")
    if not air:
        return True
    dt = _parse_air_date(air)
    if dt is None:
        return True
    return dt <= datetime.now(timezone.utc)


def episode_can_prefetch(episode: dict, check_aired: bool) -> bool:
    """When check_aired is disabled, everything is eligible (original
    behaviour). When enabled, only episodes with a valid, already-past air
    date are eligible -- episodes with no air date info are excluded."""
    if not check_aired:
        return True
    air = episode.get("airDateUtc") or episode.get("airDate")
    if not air:
        return False
    dt = _parse_air_date(air)
    if dt is None:
        return False
    return dt <= datetime.now(timezone.utc)


def season_is_fully_aired(season: dict) -> bool:
    stats = season.get("statistics")
    if not stats:
        return True
    return stats.get("nextAiring") is None


def find_season(series: dict, season_number: int) -> Optional[dict]:
    for s in series.get("seasons", []):
        if s.get("seasonNumber") == season_number:
            return s
    return None


def is_tagged_with(series: dict, tag_id: Optional[int]) -> Optional[bool]:
    if tag_id is None:
        return None
    tags = series.get("tags")
    if tags is None:
        return None
    return tag_id in tags


def episode_window(season_start: int, episode_start: int, num: int, episodes: list) -> list:
    """Return up to `num` episodes strictly following (season_start,
    episode_start) in playback order, stopping at the first gap in the
    numbering (a still-unannounced episode)."""
    episodes = sorted(episodes, key=lambda e: (e["seasonNumber"], e["episodeNumber"]))

    start_idx = None
    for i, e in enumerate(episodes):
        if e["seasonNumber"] == season_start and e["episodeNumber"] == episode_start:
            start_idx = i
            break
    if start_idx is None:
        return []

    result = []
    prev_s, prev_e = season_start, episode_start
    for e in episodes[start_idx + 1 :]:
        season_delta = max(e["seasonNumber"] - prev_s, 0)
        episode_delta = max(e["episodeNumber"] - prev_e, 0)
        prev_s, prev_e = e["seasonNumber"], e["episodeNumber"]

        if (season_delta == 1 and e["episodeNumber"] == 1) or (
            season_delta == 0 and episode_delta == 1
        ):
            result.append(e)
        elif season_delta == 0 and episode_delta == 0:
            log.warning("duplicated episode listing: %s", e)
            result.append(e)
        else:
            log.error("gap in the episode listing: %s", e)
            break

        if len(result) >= num:
            break

    return result[:num]


class Client:
    def __init__(self, base_url: str, api_key: str, session: aiohttp.ClientSession):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.session = session

    def _headers(self):
        return {"X-Api-Key": self.api_key, "Accept": "application/json"}

    def _url(self, *parts: str) -> str:
        return "/".join([self.base_url, "api", "v3", *parts])

    async def probe(self) -> None:
        async with self.session.get(
            f"{self.base_url}/api", headers=self._headers()
        ) as resp:
            resp.raise_for_status()

    async def series(self) -> list:
        async with self.session.get(self._url("series"), headers=self._headers()) as resp:
            resp.raise_for_status()
            data = await resp.json()
        out = []
        for s in data:
            if "id" in s and "seasons" in s:
                out.append(s)
            else:
                log.debug("ignoring malformed series entry: %s", s)
        return out

    async def put_series(self, series: dict) -> dict:
        url = self._url("series", str(series["id"]))
        async with self.session.put(url, headers=self._headers(), json=series) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def tags(self) -> list:
        async with self.session.get(self._url("tag"), headers=self._headers()) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def resolve_tag(self, label: str) -> Optional[int]:
        for t in await self.tags():
            if t.get("label") == label:
                return t["id"]
        return None

    async def update_tag(self, tag: dict) -> None:
        """`tag` is {"label": str, "id": Optional[int]}, mutated in place once
        resolved. Mirrors the Rust `Tag::Label -> Tag::Id` resolution -- not a
        hard error if unresolved, since the tag may appear in Sonarr later."""
        if tag.get("id") is not None:
            return
        try:
            resolved = await self.resolve_tag(tag["label"])
            if resolved is not None:
                tag["id"] = resolved
            else:
                log.warning("cannot resolve tag ID: tag=%s not known", tag["label"])
        except Exception as err:
            log.warning("cannot resolve tag ID: %s", err)

    async def _set_monitored_episodes(self, episode_ids: list, monitored: bool) -> None:
        url = self._url("episode", "monitor")
        body = {"episodeIds": episode_ids, "monitored": monitored}
        async with self.session.put(url, headers=self._headers(), json=body) as resp:
            resp.raise_for_status()

    async def update_episode_monitoring(self, episodes: list) -> None:
        monitored_ids = [e["id"] for e in episodes if e.get("monitored")]
        unmonitored_ids = [e["id"] for e in episodes if not e.get("monitored")]
        if monitored_ids:
            await self._set_monitored_episodes(monitored_ids, True)
        if unmonitored_ids:
            await self._set_monitored_episodes(unmonitored_ids, False)

    async def episodes(self, series_id: int) -> list:
        url = self._url("episode")
        async with self.session.get(
            url, headers=self._headers(), params={"seriesId": series_id}
        ) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def episodes_season(self, series_id: int, season_number: int) -> list:
        url = self._url("episode")
        params = {"seriesId": series_id, "seasonNumber": season_number}
        async with self.session.get(url, headers=self._headers(), params=params) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def episode_range(
        self, series: dict, season_start: int, episode_start: int, num: int
    ) -> list:
        episodes = await self.episodes(series["id"])
        return episode_window(season_start, episode_start, num, episodes)

    async def monitor_unannounced_episodes(self, series: dict, check_aired: bool) -> None:
        """Make sure newly announced episodes will be monitored.
        https://forums.sonarr.tv/t/season-monitor-toggle-option-that-doesnt-change-the-existing-episode-state/30098/9
        """
        series["monitored"] = True
        series["monitorNewItems"] = "all"

        seasons = series.get("seasons", [])
        if not seasons:
            await self.put_series(series)
            return

        last_season = seasons[-1]
        last_season["monitored"] = True

        original_episodes = await self.episodes_season(series["id"], last_season["seasonNumber"])
        for e in original_episodes:
            e["monitored"] = episode_can_prefetch(e, check_aired) if check_aired else True

        await self.put_series(series)
        await self.update_episode_monitoring(original_episodes)

    async def search_episodes(self, episodes: list) -> dict:
        episode_ids = [e["id"] for e in episodes]
        log.info("Searching episodes %s", episode_ids)
        return await self.command({"name": "EpisodeSearch", "episodeIds": episode_ids})

    async def search_season(self, series: dict, season_num: int, check_aired: bool) -> dict:
        log.info("Searching season %s", season_num)
        season = find_season(series, season_num)
        if season is None:
            raise ValueError(f"there is no season {season_num}")

        if season["monitored"]:
            season_episodes = await self.episodes_season(series["id"], season_num)
            for e in season_episodes:
                if not check_aired or episode_can_prefetch(e, True):
                    e["monitored"] = True
            await self.update_episode_monitoring(season_episodes)
        else:
            season["monitored"] = True
            await self.put_series(series)

        cmd = {"name": "SeasonSearch", "seriesId": series["id"], "seasonNumber": season_num}
        return await self.command(cmd)

    async def command(self, cmd: dict) -> dict:
        url = self._url("command")
        async with self.session.post(url, headers=self._headers(), json=cmd) as resp:
            resp.raise_for_status()
            return await resp.json()
