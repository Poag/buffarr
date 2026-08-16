"""Core prefetch logic.

Given a `NowPlaying` event, looks up the series in Sonarr, checks whether the
next `prefetch_num` episodes are available, and if not asks Sonarr to search
for them (either as individual episodes or, when the season has fully aired,
as a season pack). When fewer than `prefetch_num` episodes remain announced,
falls back to monitoring the series for new seasons/episodes instead.
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Optional

from prefetch.mediaserver.base import EpisodeRef, HasPendingFlag, NowPlaying, PrefetchKey, Queue, Series
from sonarr import client as sonarr_client

log = logging.getLogger("prefetch.actor")

SEEN_RETAIN_SECONDS = 60 * 60 * 24 * 7  # 7 days


class Seen:
    """Dedup set with time-based pruning, ported from `src/util/once.rs`."""

    def __init__(self):
        self._store: dict = {}

    def once(self, key) -> bool:
        self._prune()
        existed = key in self._store
        self._store[key] = time.monotonic()
        return not existed

    def _prune(self) -> None:
        now = time.monotonic()
        expired = [k for k, t in self._store.items() if now - t > SEEN_RETAIN_SECONDS]
        for k in expired:
            del self._store[k]


@dataclass
class _Pending:
    series: Series
    owed: set = field(default_factory=set)
    last_seen: float = field(default_factory=time.monotonic)


def _find_series(series_list: list, query: Series) -> Optional[dict]:
    for s in series_list:
        if query.kind == "title":
            if s.get("title") == query.value:
                return s
        else:
            if s.get("tvdbId") == query.value:
                return s
    return None


class Actor:
    def __init__(
        self,
        sonarr: sonarr_client.Client,
        prefetch_num: int,
        request_seasons: bool,
        exclude_tag_label: Optional[str],
        check_aired: bool,
        queue: Optional[Queue],
        has_pending: HasPendingFlag,
        pending_ttl: float,
    ):
        self.sonarr = sonarr
        self.seen = Seen()
        self.prefetch_num = prefetch_num
        self.request_seasons = request_seasons
        self.exclude_tag = {"label": exclude_tag_label, "id": None} if exclude_tag_label else None
        self.check_aired = check_aired
        self.queue = queue
        self.pending: dict = {}
        self.has_pending = has_pending
        self.pending_ttl = pending_ttl

    async def prefetch(self, np: NowPlaying) -> Optional[list]:
        self._refresh_pending(np)

        try:
            pairs = await self._run_prefetch(np)
            error = None
        except Exception as e:
            pairs = None
            error = e

        if pairs and np.session_id:
            entry = self.pending.setdefault(np.session_id, _Pending(series=np.series))
            entry.owed.update(pairs)

        # Always run flush + GC, even if Sonarr work failed -- pending state
        # is independent of Sonarr success.
        await self._flush_queue(np)
        self._gc_pending()
        self._publish_has_pending()

        if error is not None:
            raise error
        return pairs

    async def _run_prefetch(self, np: NowPlaying) -> Optional[list]:
        if not self.seen.once(PrefetchKey.from_now_playing(np)):
            log.debug("skip previously processed item: %s", np)
            return None

        series = await self._find_series(np)
        log.info("title=%s now_playing=%s", series.get("title", "?"), np)

        if self.exclude_tag is not None:
            await self.sonarr.update_tag(self.exclude_tag)
            tag_id = self.exclude_tag.get("id")
            if tag_id is not None and tag_id in (series.get("tags") or []):
                log.info("excluded via tag")
                return None

        # Season 0 contains specials without any particular order.
        if np.season == 0:
            return None

        episodes = await self.sonarr.episode_range(series, np.season, np.episode, self.prefetch_num)

        if len(episodes) < self.prefetch_num:
            log.info("Not as many episodes announced, monitor new items instead")
            await self.sonarr.monitor_unannounced_episodes(series, self.check_aired)
        elif not series.get("monitored"):
            series["monitored"] = True
            await self.sonarr.put_series(series)

        missing_episodes = [e for e in episodes if not e.get("hasFile")]
        if self.check_aired:
            missing_episodes = [e for e in missing_episodes if sonarr_client.episode_can_prefetch(e, True)]

        pairs = [EpisodeRef(e["seasonNumber"], e["episodeNumber"]) for e in missing_episodes]
        episodes_to_search = []

        if self.request_seasons:
            seasons_to_search = set()
            for e in missing_episodes:
                season = sonarr_client.find_season(series, e["seasonNumber"])
                if season is not None and sonarr_client.season_is_fully_aired(season):
                    seasons_to_search.add(e["seasonNumber"])
                else:
                    episodes_to_search.append(e)

            error = False
            for season_num in sorted(seasons_to_search):
                try:
                    await self.sonarr.search_season(series, season_num, self.check_aired)
                except Exception as err:
                    log.error("skip searching for season %s: %s", season_num, err)
                    error = True
            if error:
                raise RuntimeError("failed searching one or more seasons")
        else:
            episodes_to_search = missing_episodes

        if episodes_to_search:
            for e in episodes_to_search:
                e["monitored"] = True
            await self.sonarr.update_episode_monitoring(episodes_to_search)
            await self.sonarr.search_episodes(episodes_to_search)

        return pairs

    def _refresh_pending(self, np: NowPlaying) -> None:
        if not np.session_id:
            return
        p = self.pending.get(np.session_id)
        if p is None:
            return
        # If the user switched to a different series within the same
        # session, drop stale owed pairs -- they belong to the previous show
        # and would never be resolvable in the new context.
        if p.series != np.series:
            p.series = np.series
            p.owed.clear()
        p.last_seen = time.monotonic()

    async def _flush_queue(self, np: NowPlaying) -> None:
        if self.queue is None or not np.session_id:
            return
        pending = self.pending.get(np.session_id)
        if pending is None or not pending.owed:
            return
        owed = sorted(pending.owed)
        try:
            success = await self.queue.append(np, owed)
        except Exception as e:
            log.warning("queue append failed for session %s: %s", np.session_id, e)
            return
        entry = self.pending.get(np.session_id)
        if entry is not None:
            entry.owed -= success
            if not entry.owed:
                del self.pending[np.session_id]

    def _gc_pending(self) -> None:
        now = time.monotonic()
        stale = [sid for sid, p in self.pending.items() if now - p.last_seen > self.pending_ttl]
        for sid in stale:
            del self.pending[sid]

    def _publish_has_pending(self) -> None:
        self.has_pending.set_value(bool(self.pending))

    async def _find_series(self, np: NowPlaying) -> dict:
        series_list = await self.sonarr.series()
        series = _find_series(series_list, np.series)
        if series is None:
            raise ValueError("series not found in Sonarr")
        return series
