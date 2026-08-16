from datetime import datetime, timedelta, timezone

import aiohttp
import pytest
from aioresponses import aioresponses

from core.config import CONFIG
from unmonitor import radarr_job


@pytest.fixture
def cfg(monkeypatch):
    monkeypatch.setattr(CONFIG, "ENABLE_RADARR", True)
    monkeypatch.setattr(CONFIG, "RADARR_URL", "http://radarr")
    monkeypatch.setattr(CONFIG, "RADARR_API_KEY", "key")
    monkeypatch.setattr(CONFIG, "IGNORE_TAG_NAME", "ignore")
    monkeypatch.setattr(CONFIG, "SKIP_IF_FILE", False)
    monkeypatch.setattr(CONFIG, "AUTO_TAG_NAME", "auto-unmonitored")
    monkeypatch.setattr(CONFIG, "PREFERRED_RELEASE", "either")
    monkeypatch.setattr(CONFIG, "IGNORE_INCINEMAS", False)
    monkeypatch.setattr(CONFIG, "DRY_RUN", True)
    monkeypatch.setattr(CONFIG, "DELAY_MINUTES", 120)
    monkeypatch.setattr(CONFIG, "RADARR_REMONITOR_WINDOW_DAYS", 0)
    return CONFIG


async def test_movie_with_delay_tag_uses_override(cfg, caplog):
    now = datetime.now(timezone.utc)
    release_time = (now - timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%S+00:00")

    with aioresponses() as m:
        m.get(
            "http://radarr/api/v3/tag",
            payload=[{"id": 1, "label": "auto-unmonitored"}, {"id": 2, "label": "delayby_10"}],
            repeat=True,
        )
        m.get(
            "http://radarr/api/v3/movie",
            payload=[
                {
                    "id": 99,
                    "title": "Test Movie",
                    "monitored": False,
                    "tags": [1, 2],
                    "hasFile": False,
                    "digitalRelease": release_time,
                    "physicalRelease": None,
                    "inCinemas": None,
                }
            ],
            repeat=True,
        )

        async with aiohttp.ClientSession() as session:
            with caplog.at_level("INFO", logger="radarr"):
                await radarr_job.run_once(session)

    assert any("MONITOR" in r.message for r in caplog.records)


async def test_unmonitors_before_release(cfg, caplog):
    now = datetime.now(timezone.utc)
    release_time = (now + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%S+00:00")

    with aioresponses() as m:
        m.get("http://radarr/api/v3/tag", payload=[], repeat=True)
        m.get(
            "http://radarr/api/v3/movie",
            payload=[
                {
                    "id": 1,
                    "title": "Future Movie",
                    "monitored": True,
                    "tags": [],
                    "hasFile": False,
                    "digitalRelease": release_time,
                    "physicalRelease": None,
                    "inCinemas": None,
                }
            ],
            repeat=True,
        )

        async with aiohttp.ClientSession() as session:
            with caplog.at_level("INFO", logger="radarr"):
                await radarr_job.run_once(session)

    assert any("UNMONITOR" in r.message for r in caplog.records)


async def test_ignore_tag_skips_movie(cfg, caplog):
    with aioresponses() as m:
        m.get("http://radarr/api/v3/tag", payload=[{"id": 1, "label": "ignore"}], repeat=True)
        m.get(
            "http://radarr/api/v3/movie",
            payload=[
                {
                    "id": 1,
                    "title": "Ignored Movie",
                    "monitored": True,
                    "tags": [1],
                    "hasFile": False,
                    "digitalRelease": None,
                    "physicalRelease": None,
                    "inCinemas": None,
                }
            ],
            repeat=True,
        )

        async with aiohttp.ClientSession() as session:
            with caplog.at_level("INFO", logger="radarr"):
                await radarr_job.run_once(session)

    assert any("Assessed 0" in r.message for r in caplog.records)
