# backend/app/__init__.py
import os
import logging
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate

db = SQLAlchemy()
migrate = Migrate()


def create_app(test_config=None):
    app = Flask(__name__)
    cfg = ('config.DesktopConfig' if os.getenv('FLASK_CONFIG') == 'desktop'
           else 'config.DevelopmentConfig')
    app.config.from_object(cfg)

    if test_config:
        app.config.update(test_config)

    # Fail only after test_config has had a chance to provide an isolated test
    # database. Desktop mode always has a SQLite URI and needs no password.
    if app.config.get('SQLALCHEMY_DATABASE_URI') is None:
        raise RuntimeError(
            "No development database configured. Set DB_PASSWORD in an "
            "untracked .env file (see the repository .env.example). "
            "Desktop mode uses SQLite and needs no database password."
        )

    db.init_app(app)
    migrate.init_app(app, db)

    from .routes import bp as routes_bp
    app.register_blueprint(routes_bp)

    # Device integrations (Starlink / Bolero / Stardust). Cross-platform,
    # read-only, with a SIM mode, so they register unconditionally.
    from .device_routes import devices as devices_bp
    app.register_blueprint(devices_bp)

    from .dymo_routes import dymo as dymo_bp
    app.register_blueprint(dymo_bp)

    from .dymo_routes import csv_sources as dymo_csv_bp
    app.register_blueprint(dymo_csv_bp)

    # The network monitor (ARP scanner, sACN listener, /api/network/*) registers
    # only when enabled (desktop, or dev — see config.ENABLE_NETWORK_TOOLS, on by
    # default there). On a hosted deploy it'd shell out to arp/ping/netsh and 500,
    # so FIVE12_NETWORK_TOOLS=0 turns it off and the routes simply don't exist.
    if app.config.get('ENABLE_NETWORK_TOOLS'):
        from .network_routes import net as network_bp
        app.register_blueprint(network_bp)

    app.logger.setLevel(logging.INFO)

    if not app.config.get('TESTING') and app.config.get('ENABLE_NETWORK_TOOLS'):
        # Ensure the schema exists BEFORE the scanner's first tick, so a
        # first-ever desktop launch doesn't log "no such table". SQLite/desktop
        # only — dev/MySQL owns its schema through Alembic migrations, so we
        # must not create_all() there and step on it.
        if str(app.config.get('SQLALCHEMY_DATABASE_URI', '')).startswith('sqlite'):
            with app.app_context():
                db.create_all()
        # start_scanner spawns a background thread per process — under gunicorn
        # every worker runs its own scanner.
        from .scanner import start_scanner
        start_scanner(app)

        # Passive sACN listener. Same per-process caveat as the scanner: under
        # gunicorn each worker keeps its own registry, so successive polls can
        # hit workers with slightly different state. Harmless for a live view,
        # and desktop mode — the actual target — is single-process.
        # Port 5568; no collision with the Art-Net path on 6454.
        from .sacn_listener import start_sacn_listener
        start_sacn_listener(app)

    return app
