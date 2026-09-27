# Handoff — where Finsona AI stands

_Last updated: 2026-09-27, after commit `158a08e`._

## What it is
Finsona AI turns an SME's messy bank statements into a verified cash-flow picture and a safe loan size a bank
credit analyst (CA) can defend. Pipeline: PDF statements (digital or scanned) → parse with pixel coordinates →
forensic engine (own-account transfer loops, owner/family money, household spending, debt) → revenue tiers
triangulated against PromptBiz e-invoices and ภ.พ.30 VAT filings → DSCR/DSR sizing with stress tests and a
structured offer (term loan + Trade Line) → CA judgement on a watchlist → signed credit memo PDF → hand-off to the
bank's loan system (LOS). Every number traces back to highlighted rows on the source PDF.

## Stack
FastAPI + SQLAlchemy 2 (SQLite) + pydantic 2 backend (`backend/app`), React 19 + Vite + Tailwind v4 +
TanStack Query + openapi-fetch frontend (`frontend/src`), types generated from `backend/openapi.json`.
Playwright e2e in `e2e/` (uses installed Chrome). Commands: see `README.md` (`npm run dev`, `seed`, `demo:reset`,
`test`, `e2e`, `start`).

## Demo data
- **Case 1 — บริษัท กิตติ อินทีเรีย ดีไซน์** (the pitch case, SME portal): 4 statements (one password-protected),
  6 ภ.พ.30, PromptBiz invoices. Numbers fixed by `docs/BACKLOG.md` §3.
- **Case 2 — บริษัท สมใจ ฟู้ดส์** (RM-sourced): same structure at another scale; its SCB statement is a
  *scanned* image PDF → OCR review queue (11 rows pending).
- Demo logins (password `finsona-demo`): `ca`, `rm`, `sme`, `auditor`. Header ↺ (CA, demo mode) resets
  everything in ~0.1 s from the snapshot `npm run seed` takes.

## Demo script (what the e2e test clicks)
1. Pipeline strip: 10 real PDFs → 1,205 rows parsed.
2. Loop graph: 3.8M of circular transfers between own accounts, removed from revenue.
3. Click a Tier 1 figure → rows sum exactly → click a row → highlighted line on the original PDF.
4. Sizing: 5.0M requested → DSCR 1.05 (fails 1.25); "use safe limit" → 3.5M at DSCR 1.35 + 1.0M Trade Line.
5. Watchlist: accept the 450k receipt with a reason → safe limit rises to 4.14M, audit-logged.
6. Memo: sign structured approval → PDF with evidence appendix → send to LOS (reference LOS-YYYY-NNNNNN).
7. Case 2: OCR tab — OCR read 2,954.19 where the scan shows 2,954.79; correct it against the image.

## Done (increments I0–I7 + P2 batch)
Ingest (auto-detect, passwords, SHA-256, encrypted at rest), synthetic statement/ภ.พ.30 generator, parser with
bboxes, OCR path (sandbox replays recorded responses keyed by SHA-256; Azure Document Intelligence adapter
untested — no key), OCR confidence gating + review queue (uncertain amounts held out of all figures; memo signing
blocked while pending), duplicate pages / overlapping statements / coverage gaps, transfer-loop detection, owner &
household rules, revenue tiers, watchlist + CA decisions + tag overrides, customer concentration, anomaly flags,
alt-data (utility bills) haircut + EWS, cash-pattern detector, explainable drivers, DSCR/DSR sizing + stress +
structure, versioned credit policy, LLM gateway (Claude, PII-masked, cached to `data/llm_cache.json`, template mode
without a key), credit memo PDF (1 page + evidence appendix), LOS export (sandbox, idempotent), auth + roles +
case scoping, PDPA consents, hash-chained audit log + CSV, compliance/metrics/policy pages, RM field app, SME
portal, eval harness (`python -m app.eval.run`, 50 synthetic cases), instant demo reset, offline mode,
Playwright e2e, single-process prod server (`npm start`) + Dockerfile.

Test counts at handoff: 181 backend, 13 frontend, 3 e2e — all green.

## Next (remaining backlog, suggested order)
1. **E2-13 e-Tax invoice ingest** (XML/PDF) — more Tier 1 evidence; reuse ingest + parser registry.
2. **E2-14 utility bill ingest** (PDF/photo) — feeds the alt-data rules; reuse the OCR path.
3. E3-04 dStatement sandbox connector (bank-to-bank statement pull, same connector pattern as PromptBiz).
4. E8-12 case comparison · E8-13 Thai/English toggle · E7-05 watchlist evidence hint · E0-07 background jobs.

Blocked on the team (not code): real-bank statement parsers need real sample statements (T-01); LINE integration
needs a LINE Official Account; backup demo video needs `npx playwright install ffmpeg` then `npm run e2e:record`.

## Not verified
Dockerfile never built (Docker Desktop was off). Azure OCR adapter never called live. Live LLM path only tested
with injected fakes (no API key) — the demo runs in template/cache mode.
