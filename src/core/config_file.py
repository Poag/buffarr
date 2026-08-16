"""Optional TOML config file support, as an alternative to setting individual
environment variables.

Three ways to point at a file's worth of configuration:

- `BUFFARR_CONFIG_DIR=/config` -- treat that as a single Docker-style config
  volume, structured like:

      /config
      ├── conf/           # config.toml or buffarr.toml lives here
      └── logs/           # rotating buffarr.log written here

  This is the recommended way to wire up a Docker volume: mount the whole
  folder rather than bind-mounting individual files, so files can be
  added/edited/renamed on the host without touching the container's mount
  config, and without Docker silently creating an empty directory if a
  bind-mounted file doesn't exist yet at container-create time. The `conf/`
  file is optional -- BUFFARR_CONFIG_DIR can be set purely to get file
  logging under `logs/`, with all settings still coming from environment
  variables.
- `BUFFARR_CONFIG_FILE=/path/to/config.toml` -- read TOML from that exact
  file (no `logs/` output).
- `BUFFARR_CONFIG='...'` -- the environment variable's value IS the TOML
  text itself (handy for docker-compose without a volume mount).

`--config PATH` on the command line sets `BUFFARR_CONFIG_DIR` or
`BUFFARR_CONFIG_FILE` before this runs, depending on whether PATH is a
directory or a file (see `main.py`).

Keys in the TOML file must match the environment variable names documented
in the README exactly (case-insensitive) -- `[section]` tables are purely
for readability and are flattened away, so `[prefetch] ENABLE_PREFETCH = true`
and a top-level `ENABLE_PREFETCH = true` are equivalent.

`load_config_file()` must run before `core.config` (or anything importing
it) is imported anywhere, since `core.config.Config` reads `os.environ` at
class-definition time. A real environment variable that is already set
always wins over a value from the file.
"""

import os
import sys
import tomllib
from typing import Any, Optional

CONF_SUBDIR = "conf"
LOGS_SUBDIR = "logs"

# Checked in this order inside BUFFARR_CONFIG_DIR/conf/.
_CANDIDATE_FILENAMES = ("config.toml", "buffarr.toml")


def logs_dir() -> Optional[str]:
    """Return `${BUFFARR_CONFIG_DIR}/logs`, or None if BUFFARR_CONFIG_DIR
    isn't set. Used by `common.logging_setup` to enable file logging."""
    base_dir = os.environ.get("BUFFARR_CONFIG_DIR")
    if not base_dir:
        return None
    return os.path.join(base_dir, LOGS_SUBDIR)


def _find_config_in_dir(base_dir: str) -> Optional[str]:
    conf_dir = os.path.join(base_dir, CONF_SUBDIR)
    for name in _CANDIDATE_FILENAMES:
        candidate = os.path.join(conf_dir, name)
        if os.path.isfile(candidate):
            return candidate
    return None


def _flatten(data: dict) -> dict:
    out: dict = {}

    def walk(d: dict) -> None:
        for key, value in d.items():
            if isinstance(value, dict):
                walk(value)
            else:
                out[key.upper()] = value

    walk(data)
    return out


def _to_env_str(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, tuple)):
        return ",".join(str(v) for v in value)
    return str(value)


def load_config_file() -> None:
    file_path = os.environ.get("BUFFARR_CONFIG_FILE")
    base_dir = os.environ.get("BUFFARR_CONFIG_DIR")
    inline = os.environ.get("BUFFARR_CONFIG")

    if file_path:
        with open(file_path, "rb") as f:
            data = tomllib.load(f)
        source = file_path
    elif base_dir:
        resolved = _find_config_in_dir(base_dir)
        if resolved is None:
            conf_dir = os.path.join(base_dir, CONF_SUBDIR)
            tried = ", ".join(os.path.join(conf_dir, n) for n in _CANDIDATE_FILENAMES)
            print(
                f"buffarr: BUFFARR_CONFIG_DIR={base_dir} set, but none of "
                f"{tried} exist; using environment variables only",
                file=sys.stderr,
            )
            return
        with open(resolved, "rb") as f:
            data = tomllib.load(f)
        source = resolved
    elif inline:
        data = tomllib.loads(inline)
        source = "BUFFARR_CONFIG"
    else:
        return

    applied = 0
    for key, value in _flatten(data).items():
        # A real environment variable always wins over the file.
        if key not in os.environ:
            os.environ[key] = _to_env_str(value)
            applied += 1

    print(f"buffarr: loaded config from {source} ({applied} settings)", file=sys.stderr)
