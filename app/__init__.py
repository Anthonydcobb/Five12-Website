import os

from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager


db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()


def create_app():
    app = Flask(__name__)

    database_uri = os.getenv('SQLALCHEMY_DATABASE_URI')
    secret_key = os.getenv('SECRET_KEY')
    if not database_uri or not secret_key:
        raise RuntimeError(
            'Legacy Flask app requires SQLALCHEMY_DATABASE_URI and SECRET_KEY '
            'to be set in an untracked environment file.'
        )

    app.config['SQLALCHEMY_DATABASE_URI'] = database_uri
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SECRET_KEY'] = secret_key

    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)

    from app.routes import main_bp
    app.register_blueprint(main_bp)

    return app
