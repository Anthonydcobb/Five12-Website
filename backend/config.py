import os
import urllib.parse

basedir = os.path.abspath(os.path.dirname(__file__))

class DevelopmentConfig:
    DEBUG = True

    DB_USER = os.getenv("DB_USER", "root")
    DB_PASS = os.getenv("DB_PASS", "479Funtime?")
    DB_HOST = os.getenv("DB_HOST", "localhost")
    DB_NAME = os.getenv("DB_NAME", "five12_website")

    # URL-encode the password so special characters like '?' are safe
    pwd_enc = urllib.parse.quote_plus(DB_PASS)

    SQLALCHEMY_DATABASE_URI = (
        f"mysql+pymysql://{DB_USER}:{pwd_enc}@{DB_HOST}/{DB_NAME}"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
