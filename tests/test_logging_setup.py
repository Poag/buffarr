import logging
import os

from common.logging_setup import setup_logging


def _reset_root_handlers():
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)
        h.close()


def test_no_file_handler_when_config_dir_unset(monkeypatch):
    monkeypatch.delenv("BUFFARR_CONFIG_DIR", raising=False)
    _reset_root_handlers()
    try:
        setup_logging()
        assert len(logging.getLogger().handlers) == 1
        assert isinstance(logging.getLogger().handlers[0], logging.StreamHandler)
    finally:
        _reset_root_handlers()


def test_file_handler_writes_to_config_dir_logs(monkeypatch, tmp_path):
    monkeypatch.setenv("BUFFARR_CONFIG_DIR", str(tmp_path))
    _reset_root_handlers()
    try:
        setup_logging()
        log_file = tmp_path / "logs" / "buffarr.log"
        assert log_file.is_file()

        logging.getLogger("test").info("hello from the test")
        for h in logging.getLogger().handlers:
            h.flush()

        assert "hello from the test" in log_file.read_text()
    finally:
        _reset_root_handlers()


def test_setup_logging_is_idempotent_across_calls(monkeypatch, tmp_path):
    # common/logger.py calls setup_logging() eagerly at import time; main()
    # calls it again once BUFFARR_CONFIG_DIR is known. The second call must
    # fully reconfigure (force=True), not silently no-op.
    monkeypatch.delenv("BUFFARR_CONFIG_DIR", raising=False)
    _reset_root_handlers()
    try:
        setup_logging()
        assert len(logging.getLogger().handlers) == 1

        monkeypatch.setenv("BUFFARR_CONFIG_DIR", str(tmp_path))
        setup_logging()
        assert len(logging.getLogger().handlers) == 2
    finally:
        _reset_root_handlers()
