"""Entry point.

Deliberately does as little as possible at import time: config-file loading
and CLI parsing must happen before `core.config` (or anything importing it,
including `app`) is imported anywhere, since `core.config.Config` reads
`os.environ` at class-definition time. Keeping that sequencing inside
`main()` instead of at module level also keeps `import main` side-effect-free
for tests and tooling.
"""

import argparse
import asyncio
import os
import sys


def _parse_args(argv):
    parser = argparse.ArgumentParser(
        prog="buffarr",
        description="Predictive Sonarr prefetching and time-delayed "
        "Sonarr/Radarr monitoring.",
    )
    parser.add_argument(
        "--config",
        metavar="PATH",
        help="Path to a TOML config file, or to a config directory "
        "(containing conf/ and logs/ -- see BUFFARR_CONFIG_DIR in the "
        "README), as an alternative to environment variables.",
    )
    return parser.parse_args(argv)


def _apply_config_arg(path: str) -> None:
    """--config PATH: a directory means BUFFARR_CONFIG_DIR (conf/ + logs/),
    anything else is treated as a single BUFFARR_CONFIG_FILE."""
    if os.path.isdir(path):
        os.environ["BUFFARR_CONFIG_DIR"] = path
    else:
        os.environ["BUFFARR_CONFIG_FILE"] = path


def main() -> None:
    args = _parse_args(sys.argv[1:])
    if args.config:
        _apply_config_arg(args.config)

    from core.config_file import load_config_file

    load_config_file()

    from common.logging_setup import setup_logging

    setup_logging()

    from app import async_main

    try:
        asyncio.run(async_main())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
