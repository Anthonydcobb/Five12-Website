"""
Desktop entry point for Five12 Lighting.
Started by Electron. Uses SQLite, no MySQL required.
"""
import os
import sys

# Must be set before importing the app
os.environ['FLASK_CONFIG'] = 'desktop'

# Path to the built React app — Electron passes this in
static_dir = os.environ.get('FIVE12_STATIC_DIR', '')
if static_dir:
    os.environ['FIVE12_STATIC_DIR'] = static_dir

from app import create_app, db
from app.models import Fixture
from app.fixture_seed import seed_fixtures

app = create_app()

# Create tables and seed fixture library on first run
with app.app_context():
    db.create_all()
    seed_fixtures(db, Fixture)

port = int(os.environ.get('FIVE12_PORT', 5050))

print(f'[Five12] Starting on http://127.0.0.1:{port}', flush=True)
app.run(host='127.0.0.1', port=port, debug=False, use_reloader=False)
