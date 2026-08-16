import aiohttp
import pytest
from aioresponses import aioresponses

from app import _report_connection, _report_unmonitor_connections
from core.config import CONFIG


async def test_report_connection_success_logs_connected(caplog):
    with aioresponses() as m:
        m.get("http://sonarr:8989/api", status=200)
        async with aiohttp.ClientSession() as session:
            with caplog.at_level("INFO"):
                await _report_connection(session, "Sonarr", "http://sonarr:8989", "key")

    assert any(r.message == "Connected to Sonarr at http://sonarr:8989" for r in caplog.records)


async def test_report_connection_failure_warns_without_raising(caplog):
    with aioresponses() as m:
        m.get("http://sonarr:8989/api", status=500)
        async with aiohttp.ClientSession() as session:
            with caplog.at_level("WARNING"):
                await _report_connection(session, "Sonarr", "http://sonarr:8989", "key")

    assert any("Could not reach Sonarr" in r.message for r in caplog.records)


@pytest.fixture
def cfg(monkeypatch):
    monkeypatch.setattr(CONFIG, "ENABLE_SONARR", False)
    monkeypatch.setattr(CONFIG, "SONARR_URL", "")
    monkeypatch.setattr(CONFIG, "SONARR_API_KEY", "")
    monkeypatch.setattr(CONFIG, "ENABLE_RADARR", False)
    monkeypatch.setattr(CONFIG, "RADARR_URL", "")
    monkeypatch.setattr(CONFIG, "RADARR_API_KEY", "")
    monkeypatch.setattr(CONFIG, "ENABLE_PREFETCH", False)
    return CONFIG


async def test_unmonitor_connections_probes_sonarr_when_prefetch_disabled(cfg, monkeypatch, caplog):
    monkeypatch.setattr(CONFIG, "ENABLE_SONARR", True)
    monkeypatch.setattr(CONFIG, "SONARR_URL", "http://sonarr:8989")
    monkeypatch.setattr(CONFIG, "SONARR_API_KEY", "key")

    with aioresponses() as m:
        m.get("http://sonarr:8989/api", status=200)
        async with aiohttp.ClientSession() as session:
            with caplog.at_level("INFO"):
                await _report_unmonitor_connections(session)

    assert any("Connected to Sonarr" in r.message for r in caplog.records)


async def test_unmonitor_connections_skips_sonarr_when_prefetch_enabled(cfg, monkeypatch, caplog):
    # prefetch_service reports its own Sonarr connection -- app.py must not
    # duplicate that probe/log line.
    monkeypatch.setattr(CONFIG, "ENABLE_SONARR", True)
    monkeypatch.setattr(CONFIG, "SONARR_URL", "http://sonarr:8989")
    monkeypatch.setattr(CONFIG, "SONARR_API_KEY", "key")
    monkeypatch.setattr(CONFIG, "ENABLE_PREFETCH", True)

    async with aiohttp.ClientSession() as session:
        with caplog.at_level("INFO"):
            await _report_unmonitor_connections(session)

    assert not any("Sonarr" in r.message for r in caplog.records)


async def test_unmonitor_connections_probes_radarr_when_enabled(cfg, monkeypatch, caplog):
    monkeypatch.setattr(CONFIG, "ENABLE_RADARR", True)
    monkeypatch.setattr(CONFIG, "RADARR_URL", "http://radarr:7878")
    monkeypatch.setattr(CONFIG, "RADARR_API_KEY", "key")

    with aioresponses() as m:
        m.get("http://radarr:7878/api", status=200)
        async with aiohttp.ClientSession() as session:
            with caplog.at_level("INFO"):
                await _report_unmonitor_connections(session)

    assert any("Connected to Radarr" in r.message for r in caplog.records)


async def test_unmonitor_connections_noop_when_nothing_enabled(cfg, caplog):
    async with aiohttp.ClientSession() as session:
        with caplog.at_level("INFO"):
            await _report_unmonitor_connections(session)

    assert not any("Connected to" in r.message for r in caplog.records)
