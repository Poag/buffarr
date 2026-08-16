import importlib
import os


def reload_config(env: dict):
    for k, v in env.items():
        os.environ[k] = v
    import core.config as config_module

    importlib.reload(config_module)
    return config_module.CONFIG


def test_defaults(monkeypatch):
    for var in ["ENABLE_PREFETCH", "SLEEP_MINUTES", "DELAY_MINUTES", "DRY_RUN"]:
        monkeypatch.delenv(var, raising=False)
    cfg = reload_config({})
    assert cfg.SLEEP_MINUTES == 30
    assert cfg.DELAY_MINUTES == 120
    assert cfg.DRY_RUN is True
    assert cfg.ENABLE_PREFETCH is False
    assert cfg.ENABLE_SONARR is True
    assert cfg.ENABLE_RADARR is True
    assert cfg.PREFERRED_RELEASE == "either"
    assert cfg.MEDIA_SERVER_TYPE == "jellyfin"
    assert cfg.PREFETCH_NUM == 2
    assert cfg.PREFETCH_REQUEST_SEASONS is True


def test_env_overrides(monkeypatch):
    cfg = reload_config(
        {
            "ENABLE_PREFETCH": "1",
            "DRY_RUN": "0",
            "MEDIA_SERVER_USERS": "John, 12345 , Axel F",
            "MEDIA_SERVER_TYPE": "Plex",
        }
    )
    assert cfg.ENABLE_PREFETCH is True
    assert cfg.DRY_RUN is False
    assert cfg.MEDIA_SERVER_USERS == ["John", "12345", "Axel F"]
    assert cfg.MEDIA_SERVER_TYPE == "plex"
