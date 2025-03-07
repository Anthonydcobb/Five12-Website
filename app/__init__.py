from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager

db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()

def create_app():
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'mysql+pymysql://root:479Funtime?@localhost/f12l'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SECRET_KEY'] = 'your_secret_key'

    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)

    from app.routes import main_bp  # ✅ Import AFTER app is created
    app.register_blueprint(main_bp)

    return app  # ✅ Return app properly
