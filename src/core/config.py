import os


def env_bool(name: str, default: str = "0") -> bool:
    return os.environ.get(name, default).lower() in ("1", "true", "yes", "on")


def env_int(name: str, default: str = "0") -> int:
    try:
        return int(os.environ.get(name, default))
    except Exception:
        return int(default)


def env_list(name: str, default: str = "") -> list:
    raw = os.environ.get(name, default)
    return [v.strip() for v in raw.split(",") if v.strip()]


class Config:
    # ---- General ----
    TZ = os.environ.get("TZ", "UTC")
    LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
    DRY_RUN = env_bool("DRY_RUN", "1")
    WEBHOOK_PORT = env_int("WEBHOOK_PORT", "5099")

    # ---- unmonitor: time-delayed monitoring ----
    SLEEP_MINUTES = env_int("SLEEP_MINUTES", "30")
    DELAY_MINUTES = env_int("DELAY_MINUTES", "120")
    SKIP_IF_FILE = env_bool("SKIP_IF_FILE", "1")
    AUTO_TAG_NAME = os.environ.get("AUTO_TAG_NAME", "auto-unmonitored")
    IGNORE_TAG_NAME = os.environ.get("IGNORE_TAG_NAME", "ignore")

    ENABLE_RADARR = env_bool("ENABLE_RADARR", "1")
    RADARR_URL = os.environ.get("RADARR_URL", "").rstrip("/")
    RADARR_API_KEY = os.environ.get("RADARR_API_KEY", "")
    PREFERRED_RELEASE = os.environ.get("PREFERRED_RELEASE", "either").lower()
    IGNORE_INCINEMAS = env_bool("IGNORE_INCINEMAS", "0")
    RADARR_REMONITOR_WINDOW_DAYS = env_int("RADARR_REMONITOR_WINDOW_DAYS", "30")

    ENABLE_SONARR = env_bool("ENABLE_SONARR", "1")
    SONARR_URL = os.environ.get("SONARR_URL", "").rstrip("/")
    SONARR_API_KEY = os.environ.get("SONARR_API_KEY", "")
    SEASON_PACK_MODE = env_bool("SEASON_PACK_MODE", "0")
    SEASON_PACK_MODE_TAG = os.environ.get("SEASON_PACK_MODE_TAG", "season-pack")
    SONARR_REMONITOR_WINDOW_DAYS = env_int("SONARR_REMONITOR_WINDOW_DAYS", "14")

    # ---- prefetch: predictive episode fetching ----
    # Sonarr connection is shared with the unmonitor feature (SONARR_URL / SONARR_API_KEY
    # above); prefetch only needs its own toggle and behavioural knobs.
    ENABLE_PREFETCH = env_bool("ENABLE_PREFETCH", "0")

    MEDIA_SERVER_TYPE = os.environ.get("MEDIA_SERVER_TYPE", "jellyfin").lower()
    MEDIA_SERVER_URL = os.environ.get("MEDIA_SERVER_URL", "").rstrip("/")
    MEDIA_SERVER_API_KEY = os.environ.get("MEDIA_SERVER_API_KEY", "")
    MEDIA_SERVER_USERS = env_list("MEDIA_SERVER_USERS")
    MEDIA_SERVER_LIBRARIES = env_list("MEDIA_SERVER_LIBRARIES")

    PREFETCH_INTERVAL = env_int("PREFETCH_INTERVAL", "900")
    PREFETCH_NUM = env_int("PREFETCH_NUM", "2")
    PREFETCH_REQUEST_SEASONS = env_bool("PREFETCH_REQUEST_SEASONS", "1")
    PREFETCH_APPEND_TO_QUEUE = env_bool("PREFETCH_APPEND_TO_QUEUE", "0")
    PREFETCH_CHECK_AIRED = env_bool("PREFETCH_CHECK_AIRED", "0")
    PREFETCH_CONNECTION_RETRIES = env_int("PREFETCH_CONNECTION_RETRIES", "6")
    PREFETCH_EXCLUDE_TAG = os.environ.get("PREFETCH_EXCLUDE_TAG", "") or None

    def __getitem__(self, key):
        return getattr(self, key)

    def __contains__(self, key):
        return hasattr(self, key)


CONFIG = Config()
