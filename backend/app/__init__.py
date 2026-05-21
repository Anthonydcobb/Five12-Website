# backend/app/__init__.py
import os
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
import logging


db = SQLAlchemy()
migrate = Migrate()                   # ← instantiate it

def create_app(test_config=None):
    app = Flask(__name__)
    cfg = 'config.DesktopConfig' if os.getenv('FLASK_CONFIG') == 'desktop' else 'config.DevelopmentConfig'
    app.config.from_object(cfg)

    if test_config:
        app.config.update(test_config)

    # initialize extensions
    db.init_app(app)
    migrate.init_app(app, db)         # ← now migrate is defined

    # register blueprints
    from .routes import bp as routes_bp
    app.register_blueprint(routes_bp)

    from .network_routes import net as network_bp
    app.register_blueprint(network_bp)

    app.logger.setLevel(logging.INFO)

    if not app.config.get('TESTING'):
        from .scanner import start_scanner
        start_scanner(app)

    return app
