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
| `npm run seed` | Reset the database, seed the Kitti demo case and snapshot it for instant resets |
| `npm run demo:reset` | Restore the seeded demo in ~0.2 s (also: ↺ button in the header, CA in demo mode) |
| `npm test` | Backend (pytest) + frontend (Vitest) tests |
| `npm run e2e` | Browser smoke test of the five demo moments + memo signing (uses installed Chrome) |
| `npm run e2e:record` | Same, headed and slowed down, saving a video to `e2e/results/` — the backup recording. Needs `npx playwright install ffmpeg` once |
| `npm run typecheck` | TypeScript check |
| `npm run gen:api` | Regenerate frontend API types from the backend OpenAPI schema |
| `npm start` | Production: build the SPA and serve app + API from one process on http://127.0.0.1:8000 (`start:lan` for other devices, e.g. the RM phone view) |

## Demo day checklist

1. `npm run seed` once (creates the reset snapshot), then `npm run dev` or `npm start`.
2. `npm run e2e` — all five moments must pass.
3. Between run-throughs: header ↺ → click again to confirm. Resets decisions, memo, audit log and uploads; keeps AI responses.
4. Works fully offline: fonts are bundled, connectors are sandboxed, and AI narratives replay from `data/llm_cache.json` (template wording when no response is cached).

## Docker

```sh
docker build -t finsona .
docker run -p 8000:8000 -v finsona-data:/data finsona   # http://localhost:8000
```

Database, encrypted files and generated keys live in the `/data` volume. Supply `FINSONA_STORAGE_KEY` / `FINSONA_SECRET_KEY` to use your own keys, and `FINSONA_DEMO_MODE=false` to hide demo logins and reset.

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
