import re
from datetime import datetime, timedelta, timezone

import aiohttp
import pytest
from aioresponses import aioresponses

from core.config import CONFIG
from unmonitor import sonarr_job

EPISODE_URL = re.compile(r"^http://sonarr/api/v3/episode(\?.*)?$")


@pytest.fixture
def cfg(monkeypatch):
    monkeypatch.setattr(CONFIG, "ENABLE_SONARR", True)
    monkeypatch.setattr(CONFIG, "SONARR_URL", "http://sonarr")
    monkeypatch.setattr(CONFIG, "SONARR_API_KEY", "key")
    monkeypatch.setattr(CONFIG, "IGNORE_TAG_NAME", "ignore")
    monkeypatch.setattr(CONFIG, "SKIP_IF_FILE", False)
    monkeypatch.setattr(CONFIG, "AUTO_TAG_NAME", "auto-unmonitored")
    monkeypatch.setattr(CONFIG, "DRY_RUN", True)
    monkeypatch.setattr(CONFIG, "DELAY_MINUTES", 120)
    monkeypatch.setattr(CONFIG, "SONARR_REMONITOR_WINDOW_DAYS", 0)
    monkeypatch.setattr(CONFIG, "SEASON_PACK_MODE", False)
    monkeypatch.setattr(CONFIG, "SEASON_PACK_MODE_TAG", "season-pack")
    return CONFIG


async def test_series_with_delay_tag_uses_override(cfg, caplog):
    now = datetime.now(timezone.utc)
    air_time = (now - timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%SZ")

    with aioresponses() as m:
        m.get(
            "http://sonarr/api/v3/tag",
            payload=[{"id": 1, "label": "auto-unmonitored"}, {"id": 2, "label": "delayby_10"}],
            repeat=True,
        )
        m.get(
            "http://sonarr/api/v3/series",
            payload=[
                {
                    "id": 10,
                    "title": "Test Series",
                    "monitored": True,
                    "tags": [1, 2],
                    "seasons": [{"seasonNumber": 1, "monitored": True}],
                }
            ],
            repeat=True,
        )
        m.get(
            EPISODE_URL,
            payload=[
                {
                    "id": 100,
                    "episodeNumber": 1,
                    "title": "Pilot",
                    "airDateUtc": air_time,
                    "monitored": False,
                    "hasFile": False,
                }
            ],
            repeat=True,
        )

        async with aiohttp.ClientSession() as session:
            with caplog.at_level("INFO", logger="sonarr"):
                await sonarr_job.run_once(session)

    assert any("MONITOR" in r.message for r in caplog.records)


async def test_unmonitors_before_air_date(cfg, caplog):
    now = datetime.now(timezone.utc)
    air_time = (now + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")

    with aioresponses() as m:
        m.get("http://sonarr/api/v3/tag", payload=[{"id": 1, "label": "auto-unmonitored"}], repeat=True)
        m.get(
            "http://sonarr/api/v3/series",
            payload=[
                {
                    "id": 10,
                    "title": "Test Series",
                    "monitored": True,
                    "tags": [],
                    "seasons": [{"seasonNumber": 1, "monitored": True}],
                }
            ],
            repeat=True,
        )
        m.get(
            EPISODE_URL,
            payload=[
                {
                    "id": 100,
                    "episodeNumber": 1,
                    "title": "Pilot",
                    "airDateUtc": air_time,
                    "monitored": True,
                    "hasFile": False,
                }
            ],
            repeat=True,
        )

        async with aiohttp.ClientSession() as session:
            with caplog.at_level("INFO", logger="sonarr"):
                await sonarr_job.run_once(session)

    assert any("UNMONITOR" in r.message for r in caplog.records)


async def test_unmonitored_season_defensively_unmonitors_airing_episode(cfg, caplog):
    """An episode that is individually monitored inside an *unmonitored*
    season must still be unmonitored before it airs -- Sonarr's own search
    only checks episode.monitored, not season.monitored, so leaving it
    monitored would let Sonarr grab a fake pre-release."""
    now = datetime.now(timezone.utc)
    air_time = (now + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")

    with aioresponses() as m:
        m.get("http://sonarr/api/v3/tag", payload=[{"id": 1, "label": "auto-unmonitored"}], repeat=True)
        m.get(
            "http://sonarr/api/v3/series",
            payload=[
                {
                    "id": 10,
                    "title": "Test Series",
                    "monitored": True,
                    "tags": [],
                    "seasons": [{"seasonNumber": 1, "monitored": False}],
                }
            ],
            repeat=True,
        )
        m.get(
            EPISODE_URL,
            payload=[
                {
                    "id": 100,
                    "episodeNumber": 1,
                    "title": "Pilot",
                    "airDateUtc": air_time,
                    "monitored": True,
                    "hasFile": False,
                }
            ],
            repeat=True,
        )

        async with aiohttp.ClientSession() as session:
            with caplog.at_level("INFO", logger="sonarr"):
                await sonarr_job.run_once(session)

    unmonitor_lines = [r.message for r in caplog.records if r.message.startswith("UNMONITOR")]
    assert unmonitor_lines, "expected the airing episode in the unmonitored season to be unmonitored"
    dry_run_puts = [r.message for r in caplog.records if "PUT /api/v3/episode/monitor" in r.message]
    assert any('"monitored": false' in msg and '100' in msg for msg in dry_run_puts)


async def test_unmonitored_season_never_remonitored(cfg, caplog):
    """An episode past its air date + delay in an *unmonitored* season must
    never be re-monitored, even if the series carries the auto tag and would
    otherwise be eligible -- re-monitoring it would fight the user's explicit
    decision to turn the season off."""
    now = datetime.now(timezone.utc)
    air_time = (now - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")

    with aioresponses() as m:
        m.get("http://sonarr/api/v3/tag", payload=[{"id": 1, "label": "auto-unmonitored"}], repeat=True)
        m.get(
            "http://sonarr/api/v3/series",
            payload=[
                {
                    "id": 10,
                    "title": "Test Series",
                    "monitored": True,
                    "tags": [1],  # already carries the auto tag
                    "seasons": [{"seasonNumber": 1, "monitored": False}],
                }
            ],
            repeat=True,
        )
        m.get(
            EPISODE_URL,
            payload=[
                {
                    "id": 100,
                    "episodeNumber": 1,
                    "title": "Pilot",
                    "airDateUtc": air_time,
                    "monitored": False,
                    "hasFile": False,
                }
            ],
            repeat=True,
        )

        async with aiohttp.ClientSession() as session:
            with caplog.at_level("INFO", logger="sonarr"):
                await sonarr_job.run_once(session)

    assert not any(r.message.startswith("MONITOR:") for r in caplog.records)
    assert any("SUMMARY: Assessed 1, Managed 0" in r.message for r in caplog.records)


async def test_ignore_tag_skips_series(cfg, caplog):
    with aioresponses() as m:
        m.get("http://sonarr/api/v3/tag", payload=[{"id": 1, "label": "ignore"}], repeat=True)
        m.get(
            "http://sonarr/api/v3/series",
            payload=[
                {
                    "id": 10,
                    "title": "Test Series",
                    "monitored": True,
                    "tags": [1],
                    "seasons": [{"seasonNumber": 1, "monitored": True}],
                }
            ],
            repeat=True,
        )

        async with aiohttp.ClientSession() as session:
            with caplog.at_level("INFO", logger="sonarr"):
                await sonarr_job.run_once(session)

    assert any("Assessed 0" in r.message for r in caplog.records)
