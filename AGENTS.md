# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

## Shared agent workflow — mandatory

Before planning or editing, read `docs/coordination/README.md` and every file under
`docs/coordination/active/`. Work on a dedicated `<type>/<agent>/<slug>` branch and
isolated worktree, claim reserved paths in an active-work file, and follow the
handoff, evidence-label, safety, and verification rules there. Detailed feature
plans remain under `docs/superpowers/`; link them from the active-work note rather
than duplicating them.

Do not commit directly to `main`. Do not modify a path reserved by another active
task without an explicit handoff.

## Project Overview

Five12 Lighting Playground — a full-stack web app for theatrical lighting management. Core features: show/patch sheet management, DMX fixture inventory, universe conflict detection, Excel import/export, and a label designer for printing fixture labels.

## Development Commands

**Frontend** (run inside `app/`):
```
npm run dev      # Vite dev server on http://localhost:5173
npm run build    # Production build to dist/
npm run preview  # Preview production build
```

**Backend** (run inside `backend/`):
```
flask run              # Flask dev server on http://localhost:5000
flask db migrate -m "" # Generate migration
flask db upgrade       # Apply pending migrations
flask shell            # Interactive shell with app context
```

Both servers must run concurrently during development. Vite proxies all `/api/*` requests to `http://localhost:5000`.

## Architecture

**Monorepo layout:**
- `app/` — React 19 + Vite frontend
- `backend/` — Flask + SQLAlchemy API server
- `backend/migrations/` — live Alembic database migration history

**Frontend entry:** `app/src/main.jsx` → `App.jsx` (React Router routes) → `src/pages/`

**Backend entry:** `backend/app.py` → `backend/app/__init__.py` (app factory) → `backend/app/routes.py` (all API endpoints as a Blueprint)

**Database:** MySQL, credentials in `backend/.env`. Schema managed via Flask-Migrate/Alembic in `backend/migrations/` — run `flask db` commands from `backend/`, since Flask-Migrate resolves the directory relative to the working directory.

## Data Model

- **Show** — a theater production, contains many PatchSheets
- **PatchSheet** — a document mapping fixtures to DMX universes/addresses, belongs to a Show
- **PatchRow** — one fixture entry in a PatchSheet (location, dimmer, address, channel count, mode)
- **Fixture** — inventory record for a fixture type (manufacturer, mode options, channel counts)
- **LabelTemplate** — saved label designer layout stored as JSON

## Key Frontend Modules

| File | Responsibility |
|------|---------------|
| `src/pages/PatchSheet.jsx` | Main patch editor: row CRUD, DMX conflict detection, universe visualization |
| `src/components/PatchTab.jsx` | Table UI for patch rows; drag-select, multi-edit, command palette |
| `src/components/LabelDesigner.jsx` | Drag-and-drop label field layout with react-rnd |
| `src/components/InsightsView.jsx` | Address conflict detection and usage analytics |
| `src/utils/effectMath.js` | Waveform calculations for the effect playground |

## Key Backend Modules

| File | Responsibility |
|------|---------------|
| `backend/app/models.py` | SQLAlchemy ORM models for all entities |
| `backend/app/routes.py` | All REST API routes (`/api/shows`, `/api/patch-sheets`, `/api/fixtures`, `/api/label-templates`) |
| `backend/config.py` | Database URI and Flask configuration |

## API Conventions

- All routes are prefixed `/api/`
- JSON responses use **camelCase** keys (converted from snake_case DB columns)
- Excel import expects headers at row 5 (index 4) for patch data, row 2 (index 1) for fixtures
- DMX addresses: 1–512 per universe; PatchRows track `start_address` and channel count; conflict detection is handled client-side in `PatchSheet.jsx`

## Tech Stack

**Frontend:** React 19, React Router 7, Vite 5, Tailwind CSS 4, Axios, react-rnd, lucide-react  
**Backend:** Flask 3, SQLAlchemy 2, Flask-Migrate, PyMySQL, pandas/openpyxl (Excel I/O)  
**Deployment:** Gunicorn via `Procfile` (Heroku-ready)
