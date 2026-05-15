# backend/app/__init__.py
import os
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
import logging


db = SQLAlchemy()
migrate = Migrate()                   # ← instantiate it

def create_app():
    app = Flask(__name__)
    cfg = 'config.DesktopConfig' if os.getenv('FLASK_CONFIG') == 'desktop' else 'config.DevelopmentConfig'
    app.config.from_object(cfg)

    # initialize extensions
    db.init_app(app)
    migrate.init_app(app, db)         # ← now migrate is defined

    # register blueprints
    from .routes import bp as routes_bp
    app.register_blueprint(routes_bp)
    app.logger.setLevel(logging.INFO)


    return app
