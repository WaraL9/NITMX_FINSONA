# Finsona AI

Enterprise Credit Underwriting Intelligence Platform: a copilot for bank credit analysts assessing SME loans.
AI organizes the evidence, a deterministic engine does the math, the human decides, and every number traces back to a pixel on the source document.

- Strategy: [`docs/ITMX.md`](docs/ITMX.md)
- Product backlog and sprint plan: [`docs/BACKLOG.md`](docs/BACKLOG.md)
- Canonical demo case: [`data/scenario_kitti.yaml`](data/scenario_kitti.yaml)

## Quick start

Requires Python 3.11+ and Node 20+.

```bash
npm run setup   # backend venv + deps, frontend deps, seed demo DB
npm run dev     # API on :8000, web on http://localhost:5173
```

## Commands

| Command | What it does |
|---|---|
| `npm run dev` | Start backend (FastAPI, auto-reload) and frontend (Vite) together |
| `npm run seed` | Reset the database and seed the Kitti demo case |
| `npm test` | Backend (pytest) + frontend (Vitest) tests |
| `npm run typecheck` | TypeScript check |
| `npm run gen:api` | Regenerate frontend API types from the backend OpenAPI schema |

## Layout

```
backend/          FastAPI + SQLAlchemy (SQLite)
  app/core/       money (Decimal) and Thai date utilities
  app/api/        HTTP routes
  app/models.py   domain model
  tests/          pytest
frontend/         React + TypeScript + Tailwind
  src/components/ui/  design-system primitives
  src/pages/      screens
  src/api/        typed client generated from OpenAPI
data/             demo scenarios (real statements go in data/private/, which is git-ignored)
docs/             strategy and backlog
scripts/          cross-platform dev helpers
```

## Rules of the codebase

- **Money is never a float.** Backend uses `Decimal`, stored as integer satang; the API sends money as decimal strings; the frontend only formats them.
- **The LLM never produces numbers.** It tags and writes prose; the deterministic engine calculates.
- **Every derived number keeps its source transactions**, so it can be traced to a bounding box on the original PDF.
