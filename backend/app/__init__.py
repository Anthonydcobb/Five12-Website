# backend/app/__init__.py
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate     # ← import the class

db = SQLAlchemy()
migrate = Migrate()                   # ← instantiate it

def create_app():
    app = Flask(__name__)
    app.config.from_object('config.DevelopmentConfig')

    # initialize extensions
    db.init_app(app)
    migrate.init_app(app, db)         # ← now migrate is defined

    # register blueprints
    from .routes import bp as routes_bp
    app.register_blueprint(routes_bp)

    return app
