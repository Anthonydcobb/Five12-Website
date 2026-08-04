import importlib
import os

import pytest

from app import create_app


_CONFIG_ENV_KEYS = (
    'DB_HOST', 'DB_USER', 'DB_PASSWORD', 'DB_PASS', 'DB_NAME',
    'FLASK_CONFIG', 'FIVE12_DATA_DIR', 'SECRET_KEY',
)


@pytest.fixture(autouse=True)
def restore_config_module_after_test():
    """Keep class-level config values from leaking into later tests."""
    original_env = {key: os.environ.get(key) for key in _CONFIG_ENV_KEYS}
    yield

    for key, value in original_env.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value

    import config
    importlib.reload(config)


def _reload_config(monkeypatch, **env):
    """Reload config.py with an explicit, isolated database environment."""
    for key in _CONFIG_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)

    import config
    return importlib.reload(config)


def test_development_config_has_no_uri_without_db_password(monkeypatch):
    config = _reload_config(monkeypatch)
    assert config.DevelopmentConfig.SQLALCHEMY_DATABASE_URI is None


def test_legacy_db_pass_does_not_restore_a_password_default(monkeypatch):
    config = _reload_config(monkeypatch, DB_PASS='legacy-value')
    assert config.DevelopmentConfig.SQLALCHEMY_DATABASE_URI is None


def test_development_uri_uses_db_password_and_url_encodes_it(monkeypatch):
    config = _reload_config(
        monkeypatch,
        DB_HOST='db-host',
        DB_USER='five12-user',
        DB_PASSWORD='p@ss:/?',
        DB_NAME='five12-test',
    )
    assert config.DevelopmentConfig.SQLALCHEMY_DATABASE_URI == (
        'mysql+pymysql://five12-user:p%40ss%3A%2F%3F@db-host/five12-test'
    )


def test_development_startup_fails_clearly_without_db_password(monkeypatch):
    _reload_config(monkeypatch)
    with pytest.raises(RuntimeError, match='DB_PASSWORD'):
        create_app()


def test_desktop_config_still_uses_sqlite_without_db_password(monkeypatch, tmp_path):
    data_dir = tmp_path / 'five12-data'
    config = _reload_config(
        monkeypatch,
        FLASK_CONFIG='desktop',
        FIVE12_DATA_DIR=str(data_dir),
    )
    app = create_app({'TESTING': True})
    assert app.config['SQLALCHEMY_DATABASE_URI'].startswith('sqlite:///')
    assert str(data_dir) in app.config['SQLALCHEMY_DATABASE_URI']
    assert config.DesktopConfig.DATA_DIR == str(data_dir)


# ── SECRET_KEY (W4 of the Hog import review) ─────────────────────────────────
#
# The Hog import added `SECRET_KEY = os.getenv("SECRET_KEY", "five12-development")`
# to DevelopmentConfig -- a hardcoded fallback, in the file whose whole recent
# history was fix/hermes/credential-config removing exactly that shape. Desktop
# carried a literal 'five12-desktop' from before.
#
# The key has ONE consumer: signing the fixture-import preview token in
# fixture_library_routes.py. The app uses no Flask sessions. So an unconfigured
# key can simply be generated per process -- the only consequence is that a
# preview token does not survive a restart, which is correct behaviour anyway.

_KNOWN_LITERALS = ('five12-development', 'five12-desktop')


def _fresh_config(monkeypatch, **env):
    import importlib
    for key, value in env.items():
        if value is None:
            monkeypatch.delenv(key, raising=False)
        else:
            monkeypatch.setenv(key, value)
    import config
    return importlib.reload(config)


def test_development_secret_key_is_not_a_shipped_constant(monkeypatch):
    cfg = _fresh_config(monkeypatch, SECRET_KEY=None)
    assert cfg.DevelopmentConfig.SECRET_KEY not in _KNOWN_LITERALS


def test_desktop_secret_key_is_not_a_shipped_constant(monkeypatch):
    cfg = _fresh_config(monkeypatch, SECRET_KEY=None)
    assert cfg.DesktopConfig.SECRET_KEY not in _KNOWN_LITERALS


def test_a_generated_secret_key_has_real_entropy(monkeypatch):
    cfg = _fresh_config(monkeypatch, SECRET_KEY=None)
    assert len(cfg.DevelopmentConfig.SECRET_KEY) >= 32


def test_two_processes_do_not_share_a_generated_key(monkeypatch):
    first = _fresh_config(monkeypatch, SECRET_KEY=None).DevelopmentConfig.SECRET_KEY
    second = _fresh_config(monkeypatch, SECRET_KEY=None).DevelopmentConfig.SECRET_KEY
    assert first != second


def test_a_configured_secret_key_is_still_honoured(monkeypatch):
    cfg = _fresh_config(monkeypatch, SECRET_KEY='set-by-the-operator')
    assert cfg.DevelopmentConfig.SECRET_KEY == 'set-by-the-operator'


def test_the_doctor_still_reads_secret_key_as_OPTIONAL(monkeypatch):
    """The interaction that decides how this is written.

    doctor_probe derives the .env key list by parsing config.py with ast:
    `os.getenv(K, default)` is optional, bare `os.getenv(K)` is REQUIRED. So a
    helper function would make SECRET_KEY invisible to the check, and dropping
    the default would make the doctor demand a key that is optional. The
    two-argument shape has to survive.
    """
    import importlib.util
    import sys
    from pathlib import Path

    probe_path = Path(__file__).resolve().parents[2] / 'scripts' / 'doctor_probe.py'
    spec = importlib.util.spec_from_file_location('five12_probe_for_config', probe_path)
    probe = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = probe
    spec.loader.exec_module(probe)

    source = (Path(__file__).resolve().parents[1] / 'config.py').read_text(encoding='utf-8')
    keys = probe.config_env_keys(source)

    assert 'SECRET_KEY' in keys, 'the doctor must still see the key at all'
    assert keys['SECRET_KEY'] is True, 'it has a default, so it is optional'
