"""Shared types for the prefetch media-server backends."""

import asyncio
import logging
from dataclasses import dataclass, field
from typing import AsyncIterator, Optional

log = logging.getLogger("media_server")

ACTIVE_POLL_INTERVAL = 60  # seconds


@dataclass(frozen=True)
class Series:
    """Either `Series.title("Name")` or `Series.tvdb(1234)`."""

    kind: str  # "title" | "tvdb"
    value: object

    @staticmethod
    def title(name: str) -> "Series":
        return Series("title", name)

    @staticmethod
    def tvdb(tvdb_id: int) -> "Series":
        return Series("tvdb", tvdb_id)


@dataclass(frozen=True, order=True)
class EpisodeRef:
    season: int
    episode: int

    def __str__(self) -> str:
        return f"s{self.season:02d}e{self.episode:02d}"


@dataclass(frozen=True)
class User:
    name: str
    id: str


@dataclass(frozen=True)
class NowPlaying:
    series: Series
    episode: int
    season: int
    user: User
    library: Optional[str] = None
    session_id: Optional[str] = None


@dataclass(frozen=True)
class PrefetchKey:
    """Identity used for prefetch-side dedup. Excludes `session_id` so the
    same episode is prefetched at most once across sessions and restarts."""

    series: Series
    episode: int
    season: int
    user: User
    library: Optional[str]

    @staticmethod
    def from_now_playing(np: NowPlaying) -> "PrefetchKey":
        return PrefetchKey(np.series, np.episode, np.season, np.user, np.library)


class ProvideNowPlaying:
    """Mixin: backends implement `sessions()` and `extract(session)`; this
    provides the generic fan-out with per-session error isolation."""

    async def sessions(self) -> list:
        raise NotImplementedError

    async def extract(self, session) -> NowPlaying:
        raise NotImplementedError

    async def now_playing(self) -> list:
        out = []
        for session in await self.sessions():
            try:
                out.append(await self.extract(session))
            except Exception as e:
                log.debug("Ignoring session: %s", e)
        return out


class Client(ProvideNowPlaying):
    """Base class for media server backends."""

    async def probe(self) -> None:
        raise NotImplementedError

    async def run(self) -> None:
        """Optional long-running background task (e.g. Plex's websocket
        notification listener). No-op by default."""
        await asyncio.Event().wait()

    async def probe_with_retry(self, retries: int) -> None:
        from core.retry import retry

        await retry(retries, self.probe)

    async def now_playing_updates(
        self, interval: float, has_pending: "asyncio.Event | HasPendingFlag"
    ) -> AsyncIterator[NowPlaying]:
        """Yield NowPlaying items immediately on the first poll, then wait
        `interval` seconds between subsequent polls -- except the wait is
        chopped into ACTIVE_POLL_INTERVAL-sized chunks so a flip of
        `has_pending` (set by the actor after processing, when there's still
        owed queue-append work) shortens the next poll instead of waiting out
        the full interval."""
        first = True
        while True:
            if not first:
                remaining = interval
                while remaining > 0:
                    chunk = min(remaining, ACTIVE_POLL_INTERVAL)
                    await asyncio.sleep(chunk)
                    remaining -= chunk
                    if has_pending.is_set():
                        break
            first = False

            try:
                for np in await self.now_playing():
                    yield np
            except Exception as err:
                log.error("Cannot fetch sessions from media server: %s", err)


class HasPendingFlag:
    """A tiny mutable boolean flag, simpler than asyncio.Event for this use
    (we want to *read* the latest value, not consume a one-shot signal)."""

    def __init__(self):
        self._value = False

    def set_value(self, value: bool) -> None:
        self._value = value

    def is_set(self) -> bool:
        return self._value


class Queue:
    """Backends that support appending upcoming episodes to the active
    player's queue implement this."""

    async def append(self, np: NowPlaying, episodes: list) -> set:
        raise NotImplementedError


def users_filter(users: list):
    def _filter(np: NowPlaying) -> bool:
        if not users:
            return True
        accept = np.user.id in users or np.user.name in users
        if not accept:
            log.debug("Ignoring session from unwanted user: %s", np)
        return accept

    return _filter


def libraries_filter(libraries: list):
    def _filter(np: NowPlaying) -> bool:
        if not libraries:
            return True
        accept = np.library is not None and np.library in libraries
        if not accept:
            log.debug("Ignoring session from unwanted library: %s", np)
        return accept

    return _filter
