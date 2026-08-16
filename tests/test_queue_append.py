from fake_sonarr import FakeSonarr, make_episode, make_season, make_series
from prefetch.actor import Actor
from prefetch.mediaserver.base import EpisodeRef, HasPendingFlag, NowPlaying, Series, User


class FakeQueue:
    def __init__(self):
        self.calls = []
        self._next_success = None

    def override_next(self, success):
        self._next_success = success

    async def append(self, np, episodes):
        pairs = list(episodes)
        self.calls.append((np.session_id, pairs))
        if self._next_success is not None:
            success = self._next_success
            self._next_success = None
            return success
        return set(pairs)


def np_default(**kw):
    base = dict(
        series=Series.title("TestShow"),
        episode=7,
        season=1,
        user=User(name="user", id="1"),
        library=None,
        session_id="s1",
    )
    base.update(kw)
    return NowPlaying(**base)


def default_series():
    return make_series(
        1234, "TestShow", 5678,
        [make_season(0, False, True), make_season(1, False, True), make_season(2, False, True)],
    )


def default_episodes():
    eps = []
    for s in range(1, 3):
        for e in range(1, 9):
            eps.append(make_episode(s * 10 + e, 1234, s, e, False))
    return eps


def make_actor(fake, queue, has_pending, pending_ttl=3600):
    return Actor(
        sonarr=fake,
        prefetch_num=2,
        request_seasons=True,
        exclude_tag_label=None,
        check_aired=False,
        queue=queue,
        has_pending=has_pending,
        pending_ttl=pending_ttl,
    )


async def test_queue_append_called_in_playback_order():
    fake = FakeSonarr()
    fake.add_series(default_series())
    fake.add_episodes(default_episodes())

    queue = FakeQueue()
    has_pending = HasPendingFlag()
    actor = make_actor(fake, queue, has_pending)

    await actor.prefetch(np_default())

    assert len(queue.calls) == 1
    sid, pairs = queue.calls[0]
    assert sid == "s1"
    assert pairs == [EpisodeRef(1, 8), EpisodeRef(2, 1)]
    assert has_pending.is_set() is False


async def test_queue_partial_success_retries_remaining():
    fake = FakeSonarr()
    fake.add_series(default_series())
    fake.add_episodes(default_episodes())

    queue = FakeQueue()
    has_pending = HasPendingFlag()
    actor = make_actor(fake, queue, has_pending)

    queue.override_next({EpisodeRef(1, 8)})
    np = np_default()
    await actor.prefetch(np)
    assert has_pending.is_set() is True

    await actor.prefetch(np)
    assert len(queue.calls) == 2
    assert queue.calls[1][1] == [EpisodeRef(2, 1)]
    assert has_pending.is_set() is False


async def test_queue_pending_gc_evicts_stale_entries():
    import time

    fake = FakeSonarr()
    fake.add_series(default_series())
    fake.add_episodes(default_episodes())

    queue = FakeQueue()
    has_pending = HasPendingFlag()
    actor = make_actor(fake, queue, has_pending, pending_ttl=0.05)

    queue.override_next(set())
    await actor.prefetch(np_default())
    assert has_pending.is_set() is True

    time.sleep(0.08)
    try:
        await actor.prefetch(np_default(series=Series.tvdb(99999), session_id=None))
    except Exception:
        pass  # series not found -- irrelevant, we only care that GC ran

    assert has_pending.is_set() is False


async def test_queue_no_op_without_handle():
    fake = FakeSonarr()
    fake.add_series(default_series())
    fake.add_episodes(default_episodes())

    actor = make_actor(fake, None, HasPendingFlag())
    await actor.prefetch(np_default())
