import aiohttp
import pytest
from aioresponses import aioresponses

import sonarr.client as sonarr_client_module
from core.config import CONFIG
from sonarr.client import detect_api_version, resolve_api_version


@pytest.fixture(autouse=True)
def _reset_cache(monkeypatch):
    monkeypatch.setattr(sonarr_client_module, "_cached_api_version", None)


async def test_detect_api_version_v3_for_pre_v5_sonarr():
    with aioresponses() as m:
        m.get("http://sonarr/api/v3/system/status", payload={"version": "4.0.20.3014"})
        async with aiohttp.ClientSession() as session:
            version = await detect_api_version(session, "http://sonarr", "key")
    assert version == "v3"


async def test_detect_api_version_v5_for_v5_sonarr():
    with aioresponses() as m:
        m.get("http://sonarr/api/v3/system/status", payload={"version": "5.0.0.2569"})
        async with aiohttp.ClientSession() as session:
            version = await detect_api_version(session, "http://sonarr", "key")
    assert version == "v5"


async def test_resolve_api_version_skips_detection_when_explicit(monkeypatch):
    # No aioresponses mock registered at all -- if this tried to detect
    # anyway, the unmocked request would raise.
    monkeypatch.setattr(CONFIG, "SONARR_API_VERSION", "v5")
    async with aiohttp.ClientSession() as session:
        version = await resolve_api_version(session)
    assert version == "v5"


async def test_resolve_api_version_caches_detected_value(monkeypatch):
    monkeypatch.setattr(CONFIG, "SONARR_API_VERSION", "auto")
    monkeypatch.setattr(CONFIG, "SONARR_URL", "http://sonarr")
    monkeypatch.setattr(CONFIG, "SONARR_API_KEY", "key")

    with aioresponses() as m:
        # Registered once -- a second detection call would have nothing to
        # match and raise, so this also proves the cache is used.
        m.get("http://sonarr/api/v3/system/status", payload={"version": "5.0.0.2569"})
        async with aiohttp.ClientSession() as session:
            first = await resolve_api_version(session)
            second = await resolve_api_version(session)
    assert first == "v5"
    assert second == "v5"


async def test_resolve_api_version_does_not_cache_failure(monkeypatch):
    monkeypatch.setattr(CONFIG, "SONARR_API_VERSION", "auto")
    monkeypatch.setattr(CONFIG, "SONARR_URL", "http://sonarr")
    monkeypatch.setattr(CONFIG, "SONARR_API_KEY", "key")

    async with aiohttp.ClientSession() as session:
        with aioresponses() as m:
            m.get("http://sonarr/api/v3/system/status", status=500)
            with pytest.raises(Exception):
                await resolve_api_version(session)

        # A failed attempt must not be cached -- the next call has to hit
        # the network again rather than get stuck on nothing.
        with aioresponses() as m:
            m.get("http://sonarr/api/v3/system/status", payload={"version": "3.0.1.4"})
            version = await resolve_api_version(session)
    assert version == "v3"
