"""Time-delayed Sonarr episode monitoring.

Unmonitors episodes before their air date + delay, then re-monitors them once
the threshold passes -- but only for episodes buffarr itself unmonitored
(tracked via the auto tag), and only within the configured re-monitor window.
Supports per-series `delayby_<N>` tag overrides, an ignore tag, season-pack
mode, and a dry-run mode that logs without writing.

Every season of a managed series is visited, not just monitored ones: an
episode that is individually monitored inside an unmonitored season can still
be grabbed by Sonarr's own automatic search, so such episodes are still
defensively unmonitored before they air. They are never re-monitored while
their season stays unmonitored, though.
"""

import asyncio
import json
import logging
import re
from datetime import datetime, timedelta, timezone

import aiohttp

from core.config import CONFIG

log = logging.getLogger("sonarr")
AIR_FMT = "%Y-%m-%dT%H:%M:%SZ"

_DELAY_TAG_RE = re.compile(r"^delayby_(-?\d+)$", re.IGNORECASE)


def _get_delay_override(tag_ids, id_to_label, title="unknown"):
    matches = []
    for tid in tag_ids:
        label = id_to_label.get(int(tid), "")
        m = _DELAY_TAG_RE.match(label)
        if m:
            matches.append(int(m.group(1)))
    if len(matches) > 1:
        log.info("Multiple delayby_ tags found for %s, falling back to default delay", title)
        return None
    if matches:
        log.debug("Using delay override of %d min for %s", matches[0], title)
        return timedelta(minutes=matches[0])
    return None


def _api(path: str) -> str:
    return f"{CONFIG.SONARR_URL}{path}"


class _DryResponse:
    ok = True
    status = 200

    async def json(self):
        return {}


async def _req(session: aiohttp.ClientSession, method: str, path: str, **kw):
    headers = {"X-Api-Key": CONFIG.SONARR_API_KEY}
    if method.upper() in ("POST", "PUT", "PATCH", "DELETE") and CONFIG.DRY_RUN:
        payload = kw.get("json")
        log.info("[DRY] %s %s -> %s", method.upper(), path, json.dumps(payload) if payload else "(no body)")
        return _DryResponse()
    async with session.request(method.upper(), _api(path), headers=headers, timeout=aiohttp.ClientTimeout(total=30), **kw) as resp:
        data = await resp.json()

        class Resp:
            ok = resp.ok
            status = resp.status

            async def json(self):
                return data

        return Resp()


async def _tags_map(session):
    r = await _req(session, "GET", "/api/v3/tag")
    items = await r.json()
    return {int(t["id"]): t["label"] for t in items}, {t["label"].lower(): int(t["id"]) for t in items}


async def _ensure_tag(session, label, label_to_id):
    if label.lower() in label_to_id:
        return label_to_id[label.lower()]
    if CONFIG.DRY_RUN:
        log.info('[DRY] POST /api/v3/tag -> {"label": "%s"}', label)
        return 999999
    r = await _req(session, "POST", "/api/v3/tag", json={"label": label})
    if r.ok:
        _, rev = await _tags_map(session)
        return rev.get(label.lower())
    raise RuntimeError("Failed to ensure tag")


async def _run_once_inner(session):
    id_to_label, label_to_id = await _tags_map(session)
    auto_tag_id = await _ensure_tag(session, CONFIG.AUTO_TAG_NAME, label_to_id)

    season_pack_tag_id = None
    if CONFIG.SEASON_PACK_MODE:
        season_pack_tag_id = await _ensure_tag(session, CONFIG.SEASON_PACK_MODE_TAG, label_to_id)

    remonitor_window = (
        timedelta(days=CONFIG.SONARR_REMONITOR_WINDOW_DAYS)
        if CONFIG.SONARR_REMONITOR_WINDOW_DAYS > 0
        else None
    )

    series = await (await _req(session, "GET", "/api/v3/series")).json()
    series_map = {s["id"]: s["title"] for s in series}

    series_with_auto_tag = {s["id"] for s in series if auto_tag_id in s.get("tags", [])}

    season_pack_series = set()
    if CONFIG.SEASON_PACK_MODE and season_pack_tag_id:
        season_pack_series = {s["id"] for s in series if season_pack_tag_id in s.get("tags", [])}

    series_delay_override = {}
    for s in series:
        override = _get_delay_override(s.get("tags", []), id_to_label, s.get("title", f"id:{s['id']}"))
        if override is not None:
            series_delay_override[s["id"]] = override

    # Track every season of every managed series -- not just monitored ones.
    # Sonarr's own automatic search/RSS sync grabs a release whenever the
    # *episode* is monitored, regardless of whether its season is monitored
    # (season-level monitoring is only a UI aggregate / propagation
    # mechanism, not something the grab decision checks). So an episode that
    # is individually monitored inside an unmonitored season can still be
    # downloaded early. We therefore still visit unmonitored seasons to
    # defensively unmonitor any such episode before it airs -- we just never
    # *re*-monitor episodes there (see `season_monitored` below).
    tracked = []
    for s in series:
        if not s.get("monitored"):
            continue
        if CONFIG.IGNORE_TAG_NAME and any(
            id_to_label.get(tid, "").lower() == CONFIG.IGNORE_TAG_NAME.lower() for tid in s.get("tags", [])
        ):
            continue
        seasons = s.get("seasons") or []
        if not seasons:
            continue
        for season in seasons:
            tracked.append((s["id"], season["seasonNumber"], bool(season.get("monitored"))))

    assessed = 0
    default_delay = timedelta(minutes=CONFIG.DELAY_MINUTES)
    now = datetime.now(timezone.utc)

    eps_to_monitor = []
    eps_to_unmonitor = []
    series_to_remove_tag = set()
    series_episodes_to_check = {}

    async def _ensure_series_tagged(sid):
        if CONFIG.DRY_RUN:
            return
        s = await (await _req(session, "GET", f"/api/v3/series/{sid}")).json()
        if auto_tag_id not in s.get("tags", []):
            s["tags"] = s.get("tags", []) + [auto_tag_id]
            await _req(session, "PUT", f"/api/v3/series/{sid}", json=s)

    for sid, season, season_monitored in tracked:
        eps = await (await _req(session, "GET", "/api/v3/episode", params={"seriesId": sid, "seasonNumber": season})).json()
        # Only monitored-season episodes are candidates for re-monitoring, so
        # only they matter for the tag-keep-alive scan below.
        if season_monitored:
            series_episodes_to_check.setdefault(sid, []).extend(eps)

        effective_delay = series_delay_override.get(sid, default_delay)
        use_season_pack_mode = sid in season_pack_series

        if use_season_pack_mode:
            trigger_episode = None
            for e in sorted(eps, key=lambda x: x.get("episodeNumber", 999)):
                if e.get("airDateUtc"):
                    trigger_episode = e
                    break

            if trigger_episode:
                air = trigger_episode.get("airDateUtc")
                try:
                    air_dt = datetime.strptime(air, AIR_FMT).replace(tzinfo=timezone.utc)
                except Exception:
                    continue
                threshold = air_dt + effective_delay

                if now >= threshold:
                    has_auto_tag = sid in series_with_auto_tag
                    within_window = remonitor_window is None or (now - air_dt) <= remonitor_window

                    if has_auto_tag and within_window and season_monitored:
                        season_episodes_added = 0
                        for e in eps:
                            assessed += 1
                            if not e.get("airDateUtc"):
                                continue
                            if CONFIG.SKIP_IF_FILE and e.get("hasFile"):
                                continue
                            if not e.get("monitored", False):
                                title = series_map.get(sid, "Unknown Series")
                                log.info(
                                    "MONITOR (season pack): %s – S%02dE%02d – %s",
                                    title, season, e.get("episodeNumber", "?"), e.get("title", "Unknown Title"),
                                )
                                eps_to_monitor.append(e["id"])
                                season_episodes_added += 1
                        if season_episodes_added > 0:
                            title = series_map.get(sid, "Unknown Series")
                            log.info(
                                "SEASON PACK MODE: Re-monitored %d episodes for %s S%02d",
                                season_episodes_added, title, season,
                            )
                            series_to_remove_tag.add(sid)
                else:
                    for e in eps:
                        air = e.get("airDateUtc")
                        assessed += 1
                        if not air:
                            if e.get("monitored", False):
                                title = series_map.get(sid, "Unknown Series")
                                log.info(
                                    "UNMONITOR (no air date): %s – S%02dE%02d – %s",
                                    title, season, e.get("episodeNumber", "?"), e.get("title", "Unknown Title"),
                                )
                                eps_to_unmonitor.append(e["id"])
                                await _ensure_series_tagged(sid)
                            continue
                        try:
                            air_dt = datetime.strptime(air, AIR_FMT).replace(tzinfo=timezone.utc)
                        except Exception:
                            continue
                        if now < threshold and e.get("monitored", False):
                            title = series_map.get(sid, "Unknown Series")
                            log.info(
                                "UNMONITOR: %s – S%02dE%02d – %s (airDate: %s)",
                                title, season, e.get("episodeNumber", "?"), e.get("title", "Unknown Title"), air,
                            )
                            eps_to_unmonitor.append(e["id"])
                            await _ensure_series_tagged(sid)
        else:
            for e in eps:
                air = e.get("airDateUtc")
                assessed += 1

                if not air:
                    if e.get("monitored", False):
                        title = series_map.get(sid, "Unknown Series")
                        log.info(
                            "UNMONITOR (no air date): %s – S%02dE%02d – %s",
                            title, season, e.get("episodeNumber", "?"), e.get("title", "Unknown Title"),
                        )
                        eps_to_unmonitor.append(e["id"])
                        await _ensure_series_tagged(sid)
                    continue
                try:
                    air_dt = datetime.strptime(air, AIR_FMT).replace(tzinfo=timezone.utc)
                except Exception:
                    continue
                if CONFIG.SKIP_IF_FILE and e.get("hasFile"):
                    continue
                threshold = air_dt + effective_delay
                monitored = bool(e.get("monitored", False))
                title = series_map.get(sid, "Unknown Series")

                if now >= threshold and not monitored:
                    has_auto_tag = sid in series_with_auto_tag
                    within_window = remonitor_window is None or (now - air_dt) <= remonitor_window
                    if has_auto_tag and within_window and season_monitored:
                        log.info(
                            "MONITOR: %s – S%02dE%02d – %s (airDate: %s)",
                            title, season, e.get("episodeNumber", "?"), e.get("title", "Unknown Title"), air,
                        )
                        eps_to_monitor.append(e["id"])
                        series_to_remove_tag.add(sid)
                elif now < threshold and monitored:
                    log.info(
                        "UNMONITOR: %s – S%02dE%02d – %s (airDate: %s)",
                        title, season, e.get("episodeNumber", "?"), e.get("title", "Unknown Title"), air,
                    )
                    eps_to_unmonitor.append(e["id"])
                    await _ensure_series_tagged(sid)

    if eps_to_unmonitor:
        if CONFIG.DRY_RUN:
            log.info("[DRY] PUT /api/v3/episode/monitor -> %s", json.dumps({"episodeIds": eps_to_unmonitor, "monitored": False}))
        else:
            await _req(session, "PUT", "/api/v3/episode/monitor", json={"episodeIds": eps_to_unmonitor, "monitored": False})
    if eps_to_monitor:
        if CONFIG.DRY_RUN:
            log.info("[DRY] PUT /api/v3/episode/monitor -> %s", json.dumps({"episodeIds": eps_to_monitor, "monitored": True}))
        else:
            await _req(session, "PUT", "/api/v3/episode/monitor", json={"episodeIds": eps_to_monitor, "monitored": True})

    for sid in series_to_remove_tag:
        should_keep_tag = False
        for e in series_episodes_to_check.get(sid, []):
            if e.get("monitored", False):
                continue
            if CONFIG.SKIP_IF_FILE and e.get("hasFile"):
                continue
            air = e.get("airDateUtc")
            if not air:
                continue
            try:
                air_dt = datetime.strptime(air, AIR_FMT).replace(tzinfo=timezone.utc)
                threshold = air_dt + series_delay_override.get(sid, default_delay)
                if air_dt > now:
                    should_keep_tag = True
                    break
                if now < threshold:
                    should_keep_tag = True
                    break
                within_window = remonitor_window is None or (now - air_dt) <= remonitor_window
                if within_window:
                    should_keep_tag = True
                    break
            except Exception:
                continue

        if should_keep_tag:
            log.info("Keeping auto-tag on series (episodes still need re-monitoring): %s", series_map.get(sid, f"id:{sid}"))
        else:
            if CONFIG.DRY_RUN:
                log.info("[DRY] Removing auto-tag from series: %s", series_map.get(sid, f"id:{sid}"))
            else:
                s = await (await _req(session, "GET", f"/api/v3/series/{sid}")).json()
                if auto_tag_id in s.get("tags", []):
                    s["tags"] = [t for t in s.get("tags", []) if t != auto_tag_id]
                    await _req(session, "PUT", f"/api/v3/series/{sid}", json=s)

    if eps_to_monitor or eps_to_unmonitor:
        log.info(
            "SUMMARY: Assessed %d, Managed %d, Unmonitored %d, Monitored %d",
            assessed, len(eps_to_monitor) + len(eps_to_unmonitor), len(eps_to_unmonitor), len(eps_to_monitor),
        )
    else:
        log.info("SUMMARY: Assessed %d, Managed 0, Unmonitored 0, Monitored 0", assessed)


async def run_once(session: aiohttp.ClientSession):
    log.info("Sonarr app starting…")
    if not (CONFIG.ENABLE_SONARR and CONFIG.SONARR_URL and CONFIG.SONARR_API_KEY):
        return

    for attempt in range(1, 4):
        try:
            await _run_once_inner(session)
            return
        except Exception as e:
            if attempt < 3:
                log.warning("Attempt %d/3 failed: %s", attempt, e)
                await asyncio.sleep(5)
            else:
                log.error("Failed after 3 attempts: %s", e)


async def run_job(session: aiohttp.ClientSession):
    await run_once(session)
