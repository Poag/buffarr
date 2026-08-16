<div align="center">
  <img src="assets/icon.svg" width="140" alt="buffarr icon" />
  <h1>buffarr</h1>
</div>

**buffarr** combines [prefetcharr](https://github.com/p-hueber/prefetcharr) and
[unmonitarr](https://github.com/unmonitarr/unmonitarr) into a single service
with full feature parity with both:

- **prefetch** -- watches what's playing on Jellyfin, Emby, Plex, or Tautulli
  and asks Sonarr to grab the next episodes of the show before you catch up
  to them.
- **unmonitor** -- keeps Sonarr/Radarr from grabbing fake pre-release files
  by unmonitoring content until its air/release date (plus a configurable
  delay) has actually passed, then re-monitoring it automatically.

Both features share a single Sonarr connection (`SONARR_URL` /
`SONARR_API_KEY`) and run in one process, one container, one config.

## Why combine them?

If you run Sonarr/Radarr behind public indexers, unmonitor keeps you from
grabbing fake pre-release junk. If you also stream from Jellyfin/Emby/Plex,
prefetch keeps the next few episodes of whatever you're watching ready to go
before you get there. They're complementary and commonly run side by side --
buffarr just runs them as one service instead of two.

## Quick start

```bash
cp .env.example .env
# edit .env with your Sonarr/Radarr/media-server details
docker compose up -d
```

Or run locally:

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # edit it
./run_local.sh
```

### Unraid

A Community Applications template is at
[`unraid/buffarr.xml`](unraid/buffarr.xml). To install:

1. In the Unraid Docker tab, click **Add Container**, switch to **advanced
   view**, and set **Template repositories** to
   `https://raw.githubusercontent.com/Poag/buffarr/main/unraid/buffarr.xml`
   -- or install [Community Applications](https://forums.unraid.net/topic/38582-plug-in-community-applications/)
   and search for "buffarr" once the template is submitted there.
2. Fill in `SONARR_URL` / `SONARR_API_KEY` and, if you want prefetch too,
   `ENABLE_PREFETCH` + the `MEDIA_SERVER_*` fields. Everything else has a
   working default -- click **Show more settings** for the rest (Radarr,
   delay/retention windows, tags, prefetch tuning).
3. The `/config` path maps to a single appdata folder containing
   `conf/config.toml` (optional -- see [`config.example.toml`](config.example.toml),
   an alternative to filling in every field individually) and `logs/`
   (rotating log files, written automatically).

The image runs as uid 99 / gid 100, matching Unraid's own `nobody:users`
convention, so a freshly created appdata folder is writable without any
permission fixing.

## How it works

### unmonitor

Runs on a schedule (`SLEEP_MINUTES`) and on webhook triggers from Sonarr/
Radarr (`POST /trigger/sonarr`, `POST /trigger/radarr`). For each tracked
item:

1. Before its air/release date + `DELAY_MINUTES`, it's **unmonitored** and
   tagged with `AUTO_TAG_NAME` -- Sonarr/Radarr won't search for it.
2. After the threshold passes, it's **re-monitored** (only if buffarr itself
   unmonitored it, and only within `SONARR_REMONITOR_WINDOW_DAYS` /
   `RADARR_REMONITOR_WINDOW_DAYS` of the air/release date) and the tag is
   removed.
3. Items tagged `IGNORE_TAG_NAME` are never touched.
4. A per-item `delayby_<N>` tag (e.g. `delayby_-60`) overrides
   `DELAY_MINUTES` for that series/movie.
5. Sonarr's `SEASON_PACK_MODE` re-monitors an entire season at once (for
   shows tagged `SEASON_PACK_MODE_TAG`) once the first episode's threshold
   passes, instead of episode-by-episode.
6. `DRY_RUN=1` (the default) logs every action without writing anything.

Configure Sonarr/Radarr webhooks to `POST http://buffarr:5099/trigger/sonarr`
and `.../trigger/radarr` on "On Series/Movie Add" for instant processing
instead of waiting for the next scheduled pass.

### prefetch

Polls your media server every `PREFETCH_INTERVAL` seconds for active
playback sessions. For each TV episode being watched:

1. Checks whether the next `PREFETCH_NUM` episodes are available in Sonarr.
2. If any are missing, searches for them -- as a season pack
   (`PREFETCH_REQUEST_SEASONS=1`, the default) when the season has fully
   aired, otherwise episode-by-episode.
3. If fewer than `PREFETCH_NUM` episodes are announced at all, monitors the
   series for new seasons/episodes instead of searching.
4. `PREFETCH_CHECK_AIRED=1` skips episodes whose Sonarr air date is still in
   the future.
5. `PREFETCH_EXCLUDE_TAG` skips prefetching for series carrying that Sonarr
   tag.
6. `MEDIA_SERVER_USERS` / `MEDIA_SERVER_LIBRARIES` restrict which sessions
   are watched.
7. `PREFETCH_APPEND_TO_QUEUE=1` (Jellyfin/Emby/Plex only, experimental) also
   appends the newly-available episodes to the player's active queue.

## Configuration

Configuration is via environment variables (see `.env.example` for a
complete annotated list) or, as an alternative, a TOML config file (see
`config.example.toml`). Highlights:

### Using a config file instead of environment variables

Point buffarr at a TOML file instead of setting each variable individually,
using whichever of these is most convenient:

**A config directory (recommended for Docker).** Mount one volume laid out
as:

```
/config
├── conf/
│   └── config.toml   # or buffarr.toml -- see config.example.toml
└── logs/              # rotating buffarr.log written here automatically
```

```bash
BUFFARR_CONFIG_DIR=/config python src/main.py
# or
python src/main.py --config /config
```

The Docker image already defaults `BUFFARR_CONFIG_DIR` to `/config`, so with
Docker all you need is `-v /host/path:/config` (or the `volumes:` line in
`docker-compose.yml`) -- no environment variable required.

Mounting a whole directory (rather than bind-mounting a single file) means
the file inside it can be added, edited, or renamed on the host without
touching the container's mount config, and Docker won't silently create an
empty directory if a bind-mounted file doesn't exist yet at container-create
time. `conf/config.toml` is optional -- set `BUFFARR_CONFIG_DIR` for the
`logs/` output alone and keep using environment variables for everything
else if you'd rather.

**A single file, or inline TOML text:**

```bash
# a specific file (no logs/ output this way)
python src/main.py --config config.toml
# or equivalently
BUFFARR_CONFIG_FILE=/path/to/config.toml python src/main.py

# or the TOML text inline, handy for docker-compose without a volume mount
BUFFARR_CONFIG='
[prefetch]
ENABLE_PREFETCH = true
MEDIA_SERVER_URL = "http://jellyfin:8096"
' python src/main.py
```

The Docker image ships the sample file too, at `/app/config.example.toml`, so
you can pull a starting point out of it without cloning the repo:

```bash
docker run --rm ghcr.io/poag/buffarr:latest cat /app/config.example.toml > config.toml
```

Keys in the file must match the environment variable names below exactly
(case-insensitive); `[section]` tables are purely for readability and don't
affect anything. A real environment variable that is also set always wins
over the same key in the file, so you can mix both -- e.g. keep most
settings in `conf/config.toml` and pass a secret like `SONARR_API_KEY` as a
regular environment variable.

### General

| Variable | Default | Description |
|---|---|---|
| `TZ` | `UTC` | Timezone for date calculations |
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `DRY_RUN` | `1` | unmonitor: `1` = log only, `0` = apply changes |
| `WEBHOOK_PORT` | `5099` | Webhook + health-check server port |

### unmonitor

| Variable | Default | Description |
|---|---|---|
| `SLEEP_MINUTES` | `30` | Minutes between scheduled unmonitor passes |
| `DELAY_MINUTES` | `120` | Minutes after air/release before re-monitoring (can be negative) |
| `SKIP_IF_FILE` | `1` | Skip items that already have a file |
| `AUTO_TAG_NAME` | `auto-unmonitored` | Tag applied to items buffarr unmonitored |
| `IGNORE_TAG_NAME` | `ignore` | Tag that excludes an item from unmonitor entirely |
| `ENABLE_RADARR` | `1` | Enable Radarr unmonitor |
| `RADARR_URL` / `RADARR_API_KEY` | | Radarr connection |
| `PREFERRED_RELEASE` | `either` | `either`, `digital`, or `physical` |
| `IGNORE_INCINEMAS` | `0` | Ignore cinema release dates |
| `RADARR_REMONITOR_WINDOW_DAYS` | `30` | Only re-monitor movies released within N days (`0` = unlimited) |
| `ENABLE_SONARR` | `1` | Enable Sonarr unmonitor |
| `SONARR_URL` / `SONARR_API_KEY` | | Sonarr connection (shared with prefetch) |
| `SEASON_PACK_MODE` | `0` | Re-monitor whole seasons at once |
| `SEASON_PACK_MODE_TAG` | `season-pack` | Tag marking series that use season-pack mode |
| `SONARR_REMONITOR_WINDOW_DAYS` | `14` | Only re-monitor episodes aired within N days (`0` = unlimited) |

Per-item overrides: tag a series/movie with `delayby_<N>` (e.g.
`delayby_-30`) to override `DELAY_MINUTES` just for that item.

### prefetch

| Variable | Default | Description |
|---|---|---|
| `ENABLE_PREFETCH` | `0` | Enable the prefetch feature |
| `MEDIA_SERVER_TYPE` | `jellyfin` | `jellyfin`, `emby`, `plex`, or `tautulli` |
| `MEDIA_SERVER_URL` / `MEDIA_SERVER_API_KEY` | | Media server connection (Plex: server token; Tautulli: API key) |
| `MEDIA_SERVER_USERS` | *(all)* | Comma-separated user IDs/names to watch |
| `MEDIA_SERVER_LIBRARIES` | *(all)* | Comma-separated library names to watch |
| `PREFETCH_INTERVAL` | `900` | Polling interval in seconds |
| `PREFETCH_NUM` | `2` | Episodes to keep available in advance |
| `PREFETCH_REQUEST_SEASONS` | `1` | Prefer season-pack searches over per-episode |
| `PREFETCH_APPEND_TO_QUEUE` | `0` | Append prefetched episodes to the player's queue (Jellyfin/Emby/Plex only) |
| `PREFETCH_CHECK_AIRED` | `0` | Skip episodes that haven't aired yet |
| `PREFETCH_CONNECTION_RETRIES` | `6` | Retries when initially connecting to Sonarr/media server |
| `PREFETCH_EXCLUDE_TAG` | *(none)* | Sonarr tag that excludes a series from prefetching |

#### API keys

- **Sonarr / Radarr**: `Settings -> General -> Security`
- **Jellyfin**: `Administration -> Dashboard -> Advanced -> Api Keys`
- **Emby**: gear icon -> `Advanced -> Api Keys`
- **Plex**: [extract the server token](https://www.plexopedia.com/plex-media-server/general/plex-token/#plexservertoken)
- **Tautulli**: `Settings -> Web Interface -> API`

## Migrating from prefetcharr or unmonitarr

- If you only used **unmonitarr**, your existing environment variables work
  unchanged (`SLEEP_MINUTES`, `DELAY_MINUTES`, `RADARR_*`, `SONARR_*`,
  `AUTO_TAG_NAME`, etc. are all identical). Just set `ENABLE_PREFETCH=0`
  (the default) and nothing else changes.
- If you only used **prefetcharr**, set `ENABLE_PREFETCH=1` and translate
  your TOML config to the `MEDIA_SERVER_*` / `PREFETCH_*` environment
  variables above (see `.env.example`). `ENABLE_SONARR`/`ENABLE_RADARR`
  default to `1`, so also set `DRY_RUN=1` (or configure unmonitor's
  thresholds deliberately) if you don't want the unmonitor feature acting on
  your library too.

## Development

```bash
pip install -r requirements-dev.txt
PYTHONPATH=src pytest
```

## License

MIT. See [LICENSE](LICENSE) and [ATTRIBUTION.md](ATTRIBUTION.md).
