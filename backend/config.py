import os
import urllib.parse

basedir = os.path.abspath(os.path.dirname(__file__))

class DevelopmentConfig:
    DEBUG = True

    DB_USER = os.getenv("DB_USER", "root")
    DB_PASSWORD = os.getenv("DB_PASSWORD")
    DB_HOST = os.getenv("DB_HOST", "localhost")
    DB_NAME = os.getenv("DB_NAME", "five12_website")

    SQLALCHEMY_DATABASE_URI = (
        f"mysql+pymysql://{DB_USER}:{urllib.parse.quote_plus(DB_PASSWORD)}@{DB_HOST}/{DB_NAME}"
        if DB_PASSWORD
        else None
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Gates the Windows network stack in app/__init__.py — the ARP scanner, the
    # sACN listener, and the /api/network/* blueprint. On by default for local
    # dev on the rig (and so the test suite, which exercises those routes, keeps
    # working); set FIVE12_NETWORK_TOOLS=0 to run the web app without it, e.g. a
    # hosted deploy that cannot shell out to arp/ping/netsh.
    ENABLE_NETWORK_TOOLS = os.getenv("FIVE12_NETWORK_TOOLS", "1") == "1"


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

    # The desktop app IS the network monitor — always on.
    ENABLE_NETWORK_TOOLS = True
