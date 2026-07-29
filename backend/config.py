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

    # Gates the Bluetooth stack in app/__init__.py — the bleak scan thread and
    # the /api/ble/* blueprint. OFF by default, deliberately unlike
    # ENABLE_NETWORK_TOOLS: probing the operator's own LAN is expected, but
    # starting a radio scan without being asked is not. Set FIVE12_BLE_TOOLS=1.
    ENABLE_BLE_TOOLS = os.getenv("FIVE12_BLE_TOOLS", "0") == "1"

    # Gates configuration WRITES, separately from ENABLE_BLE_TOOLS. Discovery
    # and status reads are one risk; changing a radio mid-show is another, so
    # they get separate switches. Read-only stays the default even with
    # Bluetooth fully enabled. Set FIVE12_BLE_WRITE=1.
    ENABLE_BLE_WRITE = os.getenv("FIVE12_BLE_WRITE", "0") == "1"


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

    # BLE stays opt-in even on desktop — the operator turns it on per show.
    ENABLE_BLE_TOOLS = os.getenv("FIVE12_BLE_TOOLS", "0") == "1"

    # Writes stay opt-in on desktop too — same reasoning as the dev config.
    ENABLE_BLE_WRITE = os.getenv("FIVE12_BLE_WRITE", "0") == "1"
