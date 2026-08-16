from sonarr.client import episode_can_prefetch, episode_has_aired, season_is_fully_aired


def test_episode_has_aired_no_airdate():
    assert episode_has_aired({}) is True


def test_episode_has_aired_past_date():
    assert episode_has_aired({"airDate": "2020-01-01T00:00:00Z"}) is True


def test_episode_not_aired_future_date():
    assert episode_has_aired({"airDate": "2099-01-01T00:00:00Z"}) is False


def test_episode_has_aired_invalid_date():
    assert episode_has_aired({"airDate": "invalid-date"}) is True


def test_can_prefetch_disabled_always_true():
    assert episode_can_prefetch({"airDate": "2099-01-01T00:00:00Z"}, False) is True


def test_can_prefetch_enabled_no_airdate():
    assert episode_can_prefetch({}, True) is False


def test_can_prefetch_enabled_future():
    assert episode_can_prefetch({"airDate": "2099-01-01T00:00:00Z"}, True) is False


def test_can_prefetch_enabled_past():
    assert episode_can_prefetch({"airDate": "2020-01-01T00:00:00Z"}, True) is True


def test_fully_aired_with_next_airing_null():
    season = {"statistics": {"nextAiring": None}}
    assert season_is_fully_aired(season) is True


def test_not_fully_aired_with_next_airing():
    season = {"statistics": {"nextAiring": "2025-01-01T00:00:00Z"}}
    assert season_is_fully_aired(season) is False


def test_fully_aired_with_no_statistics():
    assert season_is_fully_aired({"statistics": None}) is True
