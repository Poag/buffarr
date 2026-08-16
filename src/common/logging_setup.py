import logging
import os
from logging.handlers import TimedRotatingFileHandler

from core.config import CONFIG
from core.config_file import logs_dir

# Keep this many rotated daily log files (today's + this many previous days).
LOG_BACKUP_DAYS = 14


def setup_logging() -> None:
    handlers = [logging.StreamHandler()]

    log_dir = logs_dir()
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)
        handlers.append(
            TimedRotatingFileHandler(
                os.path.join(log_dir, "buffarr.log"),
                when="midnight",
                backupCount=LOG_BACKUP_DAYS,
                encoding="utf-8",
            )
        )

    logging.basicConfig(
        level=CONFIG.LOG_LEVEL,
        format="%(asctime)s %(levelname)s:%(name)s:%(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S%z",
        handlers=handlers,
        # setup_logging() can run more than once in a process (e.g. the
        # eager call in common/logger.py at import time, followed by main()'s
        # explicit call once BUFFARR_CONFIG_DIR/LOG_LEVEL are known) --
        # force a full reconfigure each time rather than a silent no-op.
        force=True,
    )
