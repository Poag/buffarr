import os
import textwrap

from core.config_file import load_config_file, logs_dir


def test_noop_when_nothing_configured(monkeypatch):
    monkeypatch.delenv("BUFFARR_CONFIG_FILE", raising=False)
    monkeypatch.delenv("BUFFARR_CONFIG_DIR", raising=False)
    monkeypatch.delenv("BUFFARR_CONFIG", raising=False)
    monkeypatch.delenv("SOME_UNRELATED_KEY", raising=False)
    load_config_file()
    assert "SOME_UNRELATED_KEY" not in os.environ


def test_inline_config_sets_env_vars(monkeypatch):
    monkeypatch.delenv("BUFFARR_CONFIG_FILE", raising=False)
    monkeypatch.delenv("BUFFARR_CONFIG_DIR", raising=False)
    monkeypatch.delenv("ENABLE_PREFETCH", raising=False)
    monkeypatch.delenv("PREFETCH_NUM", raising=False)
    monkeypatch.setenv(
        "BUFFARR_CONFIG",
        textwrap.dedent(
            """
            [prefetch]
            ENABLE_PREFETCH = true
            PREFETCH_NUM = 3
            """
        ),
    )

    load_config_file()

    assert os.environ["ENABLE_PREFETCH"] == "true"
    assert os.environ["PREFETCH_NUM"] == "3"


def test_real_env_var_takes_precedence_over_file(monkeypatch):
    monkeypatch.delenv("BUFFARR_CONFIG_FILE", raising=False)
    monkeypatch.delenv("BUFFARR_CONFIG_DIR", raising=False)
    monkeypatch.setenv("DELAY_MINUTES", "999")
    monkeypatch.setenv("BUFFARR_CONFIG", "DELAY_MINUTES = 5\n")

    load_config_file()

    assert os.environ["DELAY_MINUTES"] == "999"


def test_file_path_is_read(monkeypatch, tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        textwrap.dedent(
            """
            [general]
            LOG_LEVEL = "DEBUG"

            [unmonitor.sonarr]
            SONARR_URL = "http://sonarr:8989"
            SONARR_API_KEY = "abc123"
            """
        )
    )
    monkeypatch.delenv("BUFFARR_CONFIG", raising=False)
    monkeypatch.delenv("BUFFARR_CONFIG_DIR", raising=False)
    monkeypatch.delenv("LOG_LEVEL", raising=False)
    monkeypatch.delenv("SONARR_URL", raising=False)
    monkeypatch.delenv("SONARR_API_KEY", raising=False)
    monkeypatch.setenv("BUFFARR_CONFIG_FILE", str(config_path))

    load_config_file()

    assert os.environ["LOG_LEVEL"] == "DEBUG"
    assert os.environ["SONARR_URL"] == "http://sonarr:8989"
    assert os.environ["SONARR_API_KEY"] == "abc123"


def test_list_values_become_comma_joined_strings(monkeypatch):
    monkeypatch.delenv("BUFFARR_CONFIG_FILE", raising=False)
    monkeypatch.delenv("BUFFARR_CONFIG_DIR", raising=False)
    monkeypatch.delenv("MEDIA_SERVER_USERS", raising=False)
    monkeypatch.setenv("BUFFARR_CONFIG", 'MEDIA_SERVER_USERS = ["John", "12345"]\n')

    load_config_file()

    from core.config import env_list

    assert os.environ["MEDIA_SERVER_USERS"] == "John,12345"
    assert env_list("MEDIA_SERVER_USERS") == ["John", "12345"]


def test_bool_values_become_lowercase_strings(monkeypatch):
    monkeypatch.delenv("BUFFARR_CONFIG_FILE", raising=False)
    monkeypatch.delenv("BUFFARR_CONFIG_DIR", raising=False)
    monkeypatch.delenv("DRY_RUN", raising=False)
    monkeypatch.setenv("BUFFARR_CONFIG", "DRY_RUN = false\n")

    load_config_file()

    assert os.environ["DRY_RUN"] == "false"


# ---- BUFFARR_CONFIG_DIR (/config/conf, /config/logs) ----


def test_config_dir_reads_conf_config_toml(monkeypatch, tmp_path):
    conf_dir = tmp_path / "conf"
    conf_dir.mkdir()
    (conf_dir / "config.toml").write_text('SONARR_URL = "http://sonarr:8989"\n')

    monkeypatch.delenv("BUFFARR_CONFIG_FILE", raising=False)
    monkeypatch.delenv("BUFFARR_CONFIG", raising=False)
    monkeypatch.delenv("SONARR_URL", raising=False)
    monkeypatch.setenv("BUFFARR_CONFIG_DIR", str(tmp_path))

    load_config_file()

    assert os.environ["SONARR_URL"] == "http://sonarr:8989"


def test_config_dir_falls_back_to_buffarr_toml(monkeypatch, tmp_path):
    conf_dir = tmp_path / "conf"
    conf_dir.mkdir()
    (conf_dir / "buffarr.toml").write_text('SONARR_URL = "http://sonarr:9999"\n')

    monkeypatch.delenv("BUFFARR_CONFIG_FILE", raising=False)
    monkeypatch.delenv("BUFFARR_CONFIG", raising=False)
    monkeypatch.delenv("SONARR_URL", raising=False)
    monkeypatch.setenv("BUFFARR_CONFIG_DIR", str(tmp_path))

    load_config_file()

    assert os.environ["SONARR_URL"] == "http://sonarr:9999"


def test_config_dir_prefers_config_toml_over_buffarr_toml(monkeypatch, tmp_path):
    conf_dir = tmp_path / "conf"
    conf_dir.mkdir()
    (conf_dir / "config.toml").write_text('SONARR_URL = "http://from-config-toml"\n')
    (conf_dir / "buffarr.toml").write_text('SONARR_URL = "http://from-buffarr-toml"\n')

    monkeypatch.delenv("BUFFARR_CONFIG_FILE", raising=False)
    monkeypatch.delenv("BUFFARR_CONFIG", raising=False)
    monkeypatch.delenv("SONARR_URL", raising=False)
    monkeypatch.setenv("BUFFARR_CONFIG_DIR", str(tmp_path))

    load_config_file()

    assert os.environ["SONARR_URL"] == "http://from-config-toml"


def test_config_dir_without_conf_file_is_not_an_error(monkeypatch, tmp_path, capsys):
    # BUFFARR_CONFIG_DIR may be set purely to enable logs/ output, with no
    # conf/config.toml present at all -- must not raise, must not touch env.
    monkeypatch.delenv("BUFFARR_CONFIG_FILE", raising=False)
    monkeypatch.delenv("BUFFARR_CONFIG", raising=False)
    monkeypatch.delenv("SOME_UNRELATED_KEY", raising=False)
    monkeypatch.setenv("BUFFARR_CONFIG_DIR", str(tmp_path))

    load_config_file()

    assert "SOME_UNRELATED_KEY" not in os.environ
    assert "none of" in capsys.readouterr().err


def test_config_file_takes_precedence_over_config_dir(monkeypatch, tmp_path):
    conf_dir = tmp_path / "conf"
    conf_dir.mkdir()
    (conf_dir / "config.toml").write_text('SONARR_URL = "http://from-dir"\n')

    explicit_file = tmp_path / "explicit.toml"
    explicit_file.write_text('SONARR_URL = "http://from-file"\n')

    monkeypatch.delenv("BUFFARR_CONFIG", raising=False)
    monkeypatch.delenv("SONARR_URL", raising=False)
    monkeypatch.setenv("BUFFARR_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("BUFFARR_CONFIG_FILE", str(explicit_file))

    load_config_file()

    assert os.environ["SONARR_URL"] == "http://from-file"


def test_logs_dir_none_when_config_dir_unset(monkeypatch):
    monkeypatch.delenv("BUFFARR_CONFIG_DIR", raising=False)
    assert logs_dir() is None


def test_logs_dir_joins_config_dir(monkeypatch):
    monkeypatch.setenv("BUFFARR_CONFIG_DIR", "/config")
    assert logs_dir() == os.path.join("/config", "logs")
