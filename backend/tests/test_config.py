import importlib

import pytest

from app import create_app


def _reload_config(monkeypatch, **env):
    """Reload config.py with an explicit, isolated database environment."""
    for key in ('DB_HOST', 'DB_USER', 'DB_PASSWORD', 'DB_PASS', 'DB_NAME',
                'FLASK_CONFIG', 'FIVE12_DATA_DIR'):
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
