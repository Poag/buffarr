from sonarr.client import episode_window


def ep(season, episode, id=1):
    return {"id": id, "seasonNumber": season, "episodeNumber": episode, "hasFile": False, "monitored": False}


def test_episode_window_none():
    episodes = [ep(1, 1)]
    assert episode_window(1, 1, 0, episodes) == []
    assert episode_window(1, 1, 1, episodes) == []


def test_episode_window_gap_episode():
    episodes = [ep(1, 1), ep(1, 3)]
    assert episode_window(1, 1, 1, episodes) == []


def test_episode_window_gap_season():
    episodes = [ep(1, 1), ep(3, 1)]
    assert episode_window(1, 1, 1, episodes) == []


def test_episode_window_next_season():
    episodes = [ep(1, 8), ep(2, 1)]
    res = episode_window(1, 8, 1, episodes)
    assert len(res) == 1
    assert res[0]["seasonNumber"] == 2


def test_episode_window_several():
    episodes = [ep(1, 8), ep(2, 1), ep(2, 2)]
    res = episode_window(1, 8, 2, episodes)
    assert len(res) == 2
    assert res[0]["episodeNumber"] == 1
    assert res[0]["seasonNumber"] == 2
    assert res[1]["episodeNumber"] == 2
    assert res[1]["seasonNumber"] == 2


def test_episode_window_duplicate():
    episodes = [
        ep(1, 1, id=1),
        ep(1, 2, id=2),
        ep(1, 2, id=3),
        ep(1, 3, id=4),
    ]
    res = episode_window(1, 1, 3, episodes)
    assert len(res) == 3
    assert res[0]["episodeNumber"] == 2
    assert res[1]["episodeNumber"] == 2
    assert res[2]["episodeNumber"] == 3
