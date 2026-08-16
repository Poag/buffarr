import pytest

from fake_sonarr import FakeSonarr, make_episode, make_episode_with_airdate, make_season, make_series
from prefetch.actor import Actor
from prefetch.mediaserver.base import HasPendingFlag, NowPlaying, Series, User


def np_default(**kw):
    base = dict(
        series=Series.title("TestShow"),
        episode=1,
        season=1,
        user=User(name="user", id="1"),
        library=None,
        session_id=None,
    )
    base.update(kw)
    return NowPlaying(**base)


def default_series():
    return make_series(
        1234,
        "TestShow",
        5678,
        [make_season(0, False, True), make_season(1, False, True), make_season(2, False, True)],
    )


def default_episodes():
    eps = []
    for s in range(1, 3):
        for e in range(1, 9):
            eps.append(make_episode(s * 10 + e, 1234, s, e, False))
    return eps


def make_actor(fake, prefetch_num, request_seasons, exclude_tag=None, check_aired=False):
    return Actor(
        sonarr=fake,
        prefetch_num=prefetch_num,
        request_seasons=request_seasons,
        exclude_tag_label=exclude_tag,
        check_aired=check_aired,
        queue=None,
        has_pending=HasPendingFlag(),
        pending_ttl=3600,
    )


async def test_search_next():
    fake = FakeSonarr()
    fake.add_series(default_series())
    fake.add_episodes(default_episodes())

    actor = make_actor(fake, 2, True)
    await actor.prefetch(np_default(episode=7, season=1))

    assert fake.series_state(1234)["monitored"] is True
    assert fake.series_state(1234)["seasons"][1]["monitored"] is True
    assert fake.series_state(1234)["seasons"][2]["monitored"] is True
    assert fake.commands == [
        {"name": "SeasonSearch", "seriesId": 1234, "seasonNumber": 1},
        {"name": "SeasonSearch", "seriesId": 1234, "seasonNumber": 2},
    ]


async def test_search_episodes_request_seasons_off():
    fake = FakeSonarr()
    fake.add_series(default_series())
    fake.add_episodes(default_episodes())

    actor = make_actor(fake, 3, False)
    await actor.prefetch(np_default(episode=7, season=1))

    assert fake.series_state(1234)["monitored"] is True
    assert fake.episode(18)["monitored"] is True
    assert fake.episode(21)["monitored"] is True
    assert fake.episode(22)["monitored"] is True
    assert fake.episode(11)["monitored"] is False
    assert fake.commands == [{"name": "EpisodeSearch", "episodeIds": [18, 21, 22]}]


async def test_search_episodes_exceeding_falls_back_to_monitor_unannounced():
    fake = FakeSonarr()
    fake.add_series(default_series())
    fake.add_episodes(default_episodes())

    actor = make_actor(fake, 3, False)
    await actor.prefetch(np_default(episode=7, season=2))

    assert fake.series_state(1234)["monitored"] is True
    assert fake.series_state(1234)["seasons"][2]["monitored"] is True
    # monitor_unannounced_episodes monitors every episode of the last season
    # (season 2 here, since it's also the season being watched) -- both via
    # Sonarr's own season-flip propagation and the explicit follow-up PUT.
    assert fake.episode(21)["monitored"] is True
    assert fake.episode(28)["monitored"] is True
    assert fake.commands == [{"name": "EpisodeSearch", "episodeIds": [28]}]


async def test_pilot_monitors_unannounced():
    fake = FakeSonarr()
    fake.add_series(default_series())
    fake.add_episodes(default_episodes())

    actor = make_actor(fake, 2, True)
    await actor.prefetch(np_default(episode=1, season=1))

    assert fake.series_state(1234)["monitored"] is True
    assert fake.series_state(1234)["seasons"][1]["monitored"] is True
    assert fake.commands == [{"name": "SeasonSearch", "seriesId": 1234, "seasonNumber": 1}]


async def test_special_episode_skipped():
    fake = FakeSonarr()
    fake.add_series(default_series())

    actor = make_actor(fake, 2, True)
    await actor.prefetch(np_default(episode=1, season=0))

    assert fake.series_state(1234)["monitored"] is False
    assert fake.commands == []


async def test_exclude_tag_skips_series():
    fake = FakeSonarr()
    fake.add_tag(1, "no-prefetch")
    series = default_series()
    series["tags"] = [1]
    fake.add_series(series)
    fake.add_episodes(default_episodes())

    actor = make_actor(fake, 2, True, exclude_tag="no-prefetch")
    await actor.prefetch(np_default(episode=7, season=1))

    assert fake.series_state(1234)["monitored"] is False
    assert fake.commands == []


async def test_exclude_tag_allows_untagged_series():
    fake = FakeSonarr()
    fake.add_tag(1, "no-prefetch")
    fake.add_series(default_series())
    fake.add_episodes(default_episodes())

    actor = make_actor(fake, 1, True, exclude_tag="no-prefetch")
    await actor.prefetch(np_default(episode=7, season=1))

    assert fake.commands != []


async def test_deduplicate():
    fake = FakeSonarr()
    fake.add_series(default_series())
    fake.add_episodes(default_episodes())

    actor = make_actor(fake, 1, True)
    np = np_default(episode=7, season=1)
    await actor.prefetch(np)
    await actor.prefetch(np)

    assert fake.commands == [{"name": "SeasonSearch", "seriesId": 1234, "seasonNumber": 1}]


async def test_find_series_by_tvdb_id():
    fake = FakeSonarr()
    fake.add_series(default_series())
    fake.add_episodes(default_episodes())

    actor = make_actor(fake, 1, True)
    await actor.prefetch(np_default(series=Series.tvdb(5678), episode=7, season=1))

    assert fake.commands != []


async def test_series_not_found_raises():
    fake = FakeSonarr()
    fake.add_series(default_series())

    actor = make_actor(fake, 1, True)
    with pytest.raises(Exception):
        await actor.prefetch(np_default(series=Series.title("Unknown"), episode=1, season=1))


async def test_skip_downloaded_episodes():
    fake = FakeSonarr()
    fake.add_series(default_series())
    eps = default_episodes()
    eps[7]["hasFile"] = True  # s01e08
    fake.add_episodes(eps)

    actor = make_actor(fake, 2, False)
    await actor.prefetch(np_default(episode=7, season=1))

    assert fake.commands == [{"name": "EpisodeSearch", "episodeIds": [21]}]


async def test_check_aired_skips_future_episodes():
    fake = FakeSonarr()
    fake.add_series(default_series())

    eps = []
    for s in range(1, 3):
        for e in range(1, 9):
            air_date = "2099-01-01T00:00:00Z" if (s == 1 and e == 8) else None
            eps.append(make_episode_with_airdate(s * 10 + e, 1234, s, e, False, air_date))
    fake.add_episodes(eps)

    actor = make_actor(fake, 2, False, check_aired=True)
    await actor.prefetch(np_default(episode=7, season=1))

    assert fake.episode(18)["monitored"] is False
    # s02e01 has no air date at all, and check_aired treats a missing air
    # date as "not eligible" (not as "already aired"), so it's excluded too.
    assert fake.episode(21)["monitored"] is False


async def test_check_aired_disabled_processes_all():
    fake = FakeSonarr()
    fake.add_series(default_series())

    eps = []
    for s in range(1, 3):
        for e in range(1, 9):
            air_date = "2099-01-01T00:00:00Z" if (s == 1 and e == 8) else None
            eps.append(make_episode_with_airdate(s * 10 + e, 1234, s, e, False, air_date))
    fake.add_episodes(eps)

    actor = make_actor(fake, 2, False, check_aired=False)
    await actor.prefetch(np_default(episode=7, season=1))

    assert fake.episode(18)["monitored"] is True
    assert fake.episode(21)["monitored"] is True
