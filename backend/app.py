# backend/app.py
from app import create_app, db
from app.models import Cue

app = create_app()

# Optional: shell context for flask CLI
@app.shell_context_processor
def make_shell_context():
    return {'db': db, 'Cue': Cue}

if __name__ == '__main__':
    app.run()
