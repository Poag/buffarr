"""Time-delayed Radarr movie monitoring. See sonarr_job.py for the shared
design notes."""

import asyncio
import json
import logging
import re
from datetime import datetime, timedelta, timezone

import aiohttp

from core.config import CONFIG

log = logging.getLogger("radarr")

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
    return f"{CONFIG.RADARR_URL}{path}"


class _DryResponse:
    ok = True
    status = 200

    async def json(self):
        return {}


async def _req(session: aiohttp.ClientSession, method: str, path: str, **kw):
    headers = {"X-Api-Key": CONFIG.RADARR_API_KEY}
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


def _parse_iso(s):
    if not s:
        return None
    s = s.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _pick_release(movie):
    digital = _parse_iso(movie.get("digitalRelease"))
    physical = _parse_iso(movie.get("physicalRelease"))
    cinemas = _parse_iso(movie.get("inCinemas"))

    if CONFIG.PREFERRED_RELEASE == "digital":
        return digital or physical or (None if CONFIG.IGNORE_INCINEMAS else cinemas)
    if CONFIG.PREFERRED_RELEASE == "physical":
        return physical or digital or (None if CONFIG.IGNORE_INCINEMAS else cinemas)
    candidates = [d for d in (digital, physical) if d]
    if candidates:
        return min(candidates)
    return None if CONFIG.IGNORE_INCINEMAS else cinemas


def _has_file(movie):
    if "hasFile" in movie:
        return bool(movie["hasFile"])
    return bool(movie.get("movieFile"))


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


async def _apply_tags(session, movie_id, tag_id, mode):
    payload = {"movieIds": [movie_id], "tags": [tag_id], "applyTags": mode}
    await _req(session, "PUT", "/api/v3/movie/editor", json=payload)


async def _set_monitored(session, movie_id, monitored):
    await _req(session, "PUT", "/api/v3/movie/editor", json={"movieIds": [movie_id], "monitored": monitored})


async def _run_once(session: aiohttp.ClientSession):
    if not (CONFIG.ENABLE_RADARR and CONFIG.RADARR_URL and CONFIG.RADARR_API_KEY):
        return

    log.info("Radarr app starting…")

    id_to_label, label_to_id = await _tags_map(session)
    auto_tag_id = await _ensure_tag(session, CONFIG.AUTO_TAG_NAME, label_to_id)
    default_delay = timedelta(minutes=CONFIG.DELAY_MINUTES)
    remonitor_window = (
        timedelta(days=CONFIG.RADARR_REMONITOR_WINDOW_DAYS)
        if CONFIG.RADARR_REMONITOR_WINDOW_DAYS > 0
        else None
    )
    now = datetime.now(timezone.utc)

    movies = await (await _req(session, "GET", "/api/v3/movie")).json()
    assessed = managed = unmonitored = remonitored = 0
    for m in movies:
        title = m.get("title", f"id:{m.get('id')}")
        if CONFIG.IGNORE_TAG_NAME and any(
            id_to_label.get(tid, "").lower() == CONFIG.IGNORE_TAG_NAME.lower() for tid in m.get("tags", [])
        ):
            continue
        if CONFIG.SKIP_IF_FILE and _has_file(m):
            continue

        delay = _get_delay_override(m.get("tags", []), id_to_label, title) or default_delay
        release = _pick_release(m)
        monitored = bool(m.get("monitored", False))
        has_auto = auto_tag_id in set(m.get("tags", []))

        assessed += 1

        if not release:
            if monitored:
                log.info("%sUNMONITOR (no release date): %s", "[DRY] " if CONFIG.DRY_RUN else "", title)
                await _set_monitored(session, int(m["id"]), False)
                await _apply_tags(session, int(m["id"]), auto_tag_id, "add")
                managed += 1
                unmonitored += 1
            continue

        threshold = release + delay

        if monitored and now < threshold:
            log.info("%sUNMONITOR: %s until %s", "[DRY] " if CONFIG.DRY_RUN else "", title, threshold.isoformat())
            await _set_monitored(session, int(m["id"]), False)
            await _apply_tags(session, int(m["id"]), auto_tag_id, "add")
            managed += 1
            unmonitored += 1
        elif (not monitored) and has_auto and now >= threshold:
            within_window = remonitor_window is None or (now - release) <= remonitor_window
            if within_window:
                log.info("%sMONITOR: %s (past %s)", "[DRY] " if CONFIG.DRY_RUN else "", title, threshold.isoformat())
                await _set_monitored(session, int(m["id"]), True)
                await _apply_tags(session, int(m["id"]), auto_tag_id, "remove")
                managed += 1
                remonitored += 1

    log.info("SUMMARY: Assessed %d, Managed %d, Unmonitored %d, Monitored %d", assessed, managed, unmonitored, remonitored)


async def run_once(session: aiohttp.ClientSession):
    if not (CONFIG.ENABLE_RADARR and CONFIG.RADARR_URL and CONFIG.RADARR_API_KEY):
        return

    max_retries = 3
    for attempt in range(1, max_retries + 1):
        try:
            await _run_once(session)
            break
        except asyncio.TimeoutError as e:
            if attempt < max_retries:
                log.warning("Retrying after timeout… (attempt %d)", attempt)
                await asyncio.sleep(5)
            else:
                log.error("Failed after 3 attempts: %s", e)


async def run_job(session: aiohttp.ClientSession):
    log.info("Radarr job triggered via job queue")
    await run_once(session)
