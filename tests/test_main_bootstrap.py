import importlib


def test_import_is_side_effect_free(monkeypatch):
    """Importing main.py must not touch argv/env/config -- all of that has
    to stay deferred inside main() so tests (and other tooling) can import
    it safely, and so config-file loading can run before `core.config` (or
    anything importing it) is ever imported."""
    monkeypatch.delenv("BUFFARR_CONFIG_FILE", raising=False)
    import main

    importlib.reload(main)
    assert "BUFFARR_CONFIG_FILE" not in __import__("os").environ
    assert callable(main.main)


def test_parse_args_config_flag():
    import main

    args = main._parse_args(["--config", "/tmp/foo.toml"])
    assert args.config == "/tmp/foo.toml"


def test_parse_args_no_flag():
    import main

    args = main._parse_args([])
    assert args.config is None


def test_apply_config_arg_directory_sets_config_dir(monkeypatch, tmp_path):
    import main

    monkeypatch.delenv("BUFFARR_CONFIG_DIR", raising=False)
    monkeypatch.delenv("BUFFARR_CONFIG_FILE", raising=False)

    main._apply_config_arg(str(tmp_path))

    import os

    assert os.environ["BUFFARR_CONFIG_DIR"] == str(tmp_path)
    assert "BUFFARR_CONFIG_FILE" not in os.environ


def test_apply_config_arg_file_sets_config_file(monkeypatch, tmp_path):
    import main

    config_file = tmp_path / "config.toml"
    config_file.write_text("TZ = \"UTC\"\n")

    monkeypatch.delenv("BUFFARR_CONFIG_DIR", raising=False)
    monkeypatch.delenv("BUFFARR_CONFIG_FILE", raising=False)

    main._apply_config_arg(str(config_file))

    import os

    assert os.environ["BUFFARR_CONFIG_FILE"] == str(config_file)
    assert "BUFFARR_CONFIG_DIR" not in os.environ
