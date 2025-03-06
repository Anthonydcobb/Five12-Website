from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager

db = SQLAlchemy()
migrate = Migrate()  # ✅ Initialize Flask-Migrate
login_manager = LoginManager()

def create_app():
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'mysql+pymysql://root:479Funtime?@localhost/f12l'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SECRET_KEY'] = 'your_secret_key'

    db.init_app(app)
    migrate.init_app(app, db)  # ✅ Make sure migrations are initialized
    login_manager.init_app(app)

    from app.routes import main_bp  # ✅ Import the Blueprint
    app.register_blueprint(main_bp)  # ✅ Register it properly

    return app
