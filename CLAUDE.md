# Finsona AI — working notes for Claude

Hackathon (NITMX/ITMX) project: credit-underwriting copilot for bank analysts assessing Thai SME loans.
One engineer (the user) + Claude. **Start every session by reading `docs/HANDOFF.md`** — it has the current
state, what is done, and what is next. Product spec: `docs/ITMX.md` (Thai). Backlog + canonical numbers: `docs/BACKLOG.md`.

## How we work
- Build real, working software. Only external systems (PromptBiz, utility, LOS, OCR provider, dStatement) are
  mocked, as sandbox connectors with the same interface a live adapter would have. Don't cut scope.
- One backlog item (or increment) at a time → tests green → commit. Commit trailer:
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Before every commit: `npm run test:api`, `npm run test:web`, `npm run typecheck`, `npm run build`; for UI work
  also `npm run e2e`. Never commit `backend/.secret`, `backend/.storage_key`, `data/private/`, snapshots or DBs.
- After any schema change (`backend/app/models.py`): `npm run seed` (also refreshes the reset snapshot), then
  `npm run gen:api` if API shapes changed.
- UI text is Thai, always inside `tr("…")` (`@/lib/i18n`; not `t` — that is a transaction variable) with the English
  added to `frontend/src/i18n/en.ts`; `i18n.test.ts` fails otherwise. Default theme is "dim" with a light toggle.
- Backend text a user sees (reasons, signals, warnings, errors) goes in `th("…")`/`th(f"…")` (`app/core/i18n.py`,
  identity) with English added to `frontend/src/i18n/en_server.json`; `test_i18n_catalog.py` fails otherwise. Never
  wrap strings used to match bank data or to prompt the LLM.

## Rules that must not break
- **The engine does all money math, deterministically.** Money = `Decimal`, stored as integer satang, sent as
  decimal strings. The frontend never does money arithmetic. The LLM never writes numbers (narratives use
  `{{placeholders}}`; any digit outside one is rejected → template fallback).
- **Lineage invariant:** every figure maps to a transaction filter (`backend/app/api/metrics.py`) whose rows
  sum to it exactly. Anything that changes what a figure includes must change the filter too (tested).
- **Canonical Kitti case (case 1) numbers are asserted by tests** (`docs/BACKLOG.md` §3): verified revenue
  25.0M, DSCR 1.05 at 5.0M, safe limit 3.5M, accept 450k watchlist → 4.14M. Don't change `data/scenario_kitti.yaml`.
- Human-in-the-loop: every CA decision needs a reason ≥ 10 chars and goes to the hash-chained audit log.
  Audit appends must insert before reading the chain head (see `services/audit.py`) — concurrency bug otherwise.
- PII is masked before anything reaches the LLM; settings/secrets never printed.

## Environment gotchas (Windows)
- Bash here is Git Bash. No `jq` — use `backend/.venv/Scripts/python` for JSON.
- Don't put Python triple-quoted strings inside bash heredocs for patching; write the patch script to the
  scratchpad and run it with the venv Python. Set `PYTHONIOENCODING=utf-8` when printing Thai.
- Vite listens on `localhost` (IPv6), not `127.0.0.1`. API dev server: `app.devserver.run` under watchfiles
  (uvicorn `--reload` hangs on Windows).
- The machine is memory-constrained. Background dev servers get reaped under memory pressure and can leave
  orphans (`npm run dev`, watchfiles, vite) — check for and stop them before starting new ones. Prefer
  foreground test runs; `npm run e2e` starts/stops its own dev servers.
- TypeScript is pinned to ~5.9 (TS 7 breaks openapi-typescript).
