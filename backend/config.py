import os
import urllib.parse

basedir = os.path.abspath(os.path.dirname(__file__))

class DevelopmentConfig:
    DEBUG = True

    DB_USER = os.getenv("DB_USER", "root")
    DB_PASS = os.getenv("DB_PASS", "479Funtime?")
    DB_HOST = os.getenv("DB_HOST", "localhost")
    DB_NAME = os.getenv("DB_NAME", "five12_website")

    pwd_enc = urllib.parse.quote_plus(DB_PASS)
    SQLALCHEMY_DATABASE_URI = (
        f"mysql+pymysql://{DB_USER}:{pwd_enc}@{DB_HOST}/{DB_NAME}"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False


class DesktopConfig:
    DEBUG = False
    SECRET_KEY = 'five12-desktop'

    # Store the database in ~/Five12Data/five12.db
    DATA_DIR = os.getenv(
        'FIVE12_DATA_DIR',
        os.path.join(os.path.expanduser('~'), 'Five12Data')
    )
    os.makedirs(DATA_DIR, exist_ok=True)

    SQLALCHEMY_DATABASE_URI = f"sqlite:///{os.path.join(DATA_DIR, 'five12.db')}"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
