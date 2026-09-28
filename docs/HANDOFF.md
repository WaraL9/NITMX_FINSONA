# Handoff — where Finsona AI stands

_Last updated: 2026-09-28, after the E6-06 lease tenor cap — the code backlog is complete._

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
- **e-Tax invoice samples** (E2-13, not seeded — upload them in the demo): `data/generated/<case>/etax/` has 3
  invoices for Tier-2 receipts, each as ETDA XML, PDF with the XML embedded, and a printed PDF (text fallback).
  Uploading one moves its receipt from T2 to T1 after “วิเคราะห์ใหม่” (Kitti: `etax_ETX-2512-0001.xml`).
  Revenue total is unchanged (T2→T1); T1 share and the T1-based Trade Line rise. Canonical figures unaffected
  until something is uploaded.
- **Bill samples** (E2-14, not seeded): `data/generated/<case>/bills/` — electricity e-bill PDF (paid via the
  statement), water bill **phone photo** (JPEG stored sideways + EXIF flag; recorded OCR reads the amount at 41%
  confidence → held for CA review), rent **receipt** PDF (printed paid date + lease end before loan maturity →
  signal and a **tenor cap**: Kitti's 12-month loan is sized over 8 months, so the safe limit falls — a strong demo
  moment, e2e-tested). In Kitti the utility connector already has these months, so uploads show “ตรงกับข้อมูลผู้ให้บริการ”
  and the haircut is unchanged; in a case without connector data they drive the late-payment rules.
- **dStatement feed** (E3-04): `data/generated/<case>/dstatement.json` — every account's statement as the source
  bank holds it, served signed by the sandbox connector (consent purpose `dstatement_data`, granted in the seed).
- Demo logins (password `finsona-demo`): `ca`, `rm`, `sme`, `auditor`. Header ↺ (CA, demo mode) resets
  everything in ~0.1 s from the snapshot `npm run seed` takes.

## Demo script (what the e2e test clicks)
1. Pipeline strip: 10 real PDFs → 1,205 rows parsed.
2. Loop graph: 3.8M of circular transfers between own accounts, removed from revenue.
3. Click a Tier 1 figure → rows sum exactly → click a row → highlighted line on the original PDF.
4. Sizing: 5.0M requested → DSCR 1.05 (fails 1.25); "use safe limit" → 3.5M at DSCR 1.35 + 1.0M Trade Line.
5. Watchlist: accept the 450k receipt with a reason → safe limit rises to 4.14M, audit-logged. The overview's
   “เปรียบเทียบสถานการณ์” card then shows 3.5M (evidence alone) vs 4.14M (+640,000) after the decision.
6. Memo: sign structured approval → PDF with evidence appendix → send to LOS (reference LOS-YYYY-NNNNNN).
7. Case 2: OCR tab — OCR read 2,954.19 where the scan shows 2,954.79; correct it against the image.
8. (after a reset) Case 1 documents tab: drop `etax_ETX-2512-0001.xml` → “รอวิเคราะห์ใหม่” → วิเคราะห์ใหม่ →
   “ยืนยันเงินเข้า … → ระดับ 1”.
9. (after a reset) Case 1 documents tab: drop `bills/bill_water_2026-04.jpg` → วิเคราะห์ใหม่ → “รอตรวจทาน OCR” →
   ตรวจทาน → reason → “ตรงกับข้อมูลผู้ให้บริการ · CA ยืนยันแล้ว”, audit-logged.
10. dStatement: Case 1 documents → “ดึงจากธนาคาร (dStatement)” → BBL → “ไฟล์ที่อัปโหลดตรงกับธนาคาร 581/581”.
    Case 2 → SCB (the scan) → “ไม่ตรง 3 จุด” → วิเคราะห์ใหม่ → high anomaly “ไม่ตรงกับข้อมูลธนาคาร” (the OCR misreads).

## Done (increments I0–I7 + P2 batch + E2-13 + E2-14 + E3-04 + E8-12 + E8-13 + E7-05 + E0-07)
Background analysis jobs (E0-07: `POST /api/cases/{id}/analysis/jobs` → 202, poll `GET …/analysis/jobs/{job_id}`;
`services/jobs.py` runs `run_analysis` via FastAPI BackgroundTasks with a progress callback — stages sync, load, the
engine's loops/classify/tiers/aggregate laps, evidence, save. Job row written when queued and when finished; live
stage progress in a per-job file `<storage>/jobs/<id>.json` (the analysis holds SQLite's write lock until it commits),
readable by every worker; heartbeat every 5 s, a job silent for 60 s is failed (on poll and at startup). One open job
per case via a partial unique index. Verified with `uvicorn --workers 2` under concurrent starts and polling —
which found and fixed a Windows file-lock race: progress writes are best effort and can never fail a job. The workbench “วิเคราะห์ใหม่” button runs a job and shows the live stage strip (E8-03). The
synchronous `POST /analysis` and the quick re-runs after CA decisions are unchanged.)
Watchlist evidence hint (E7-05: `ai/evidence_hint.py` — one batched gateway call per case for open items, told the
business's industry; returns 1–3 documents + a question for the RM; no digits allowed — `{{amount}}` `{{date}}`
`{{counterparty}}` `{{pp30}}` placeholders filled by the engine via `narrative.fill`, invalid items fall back to a
rule-based template (cash deposit / individual / company), which is also the no-LLM mode. Stored on
`WatchlistItem.evidence_hint` at each analysis; template hints retry so they upgrade once an LLM answers. UI card in
the Watchlist detail with “ใช้ถาม RM” → fills the query reason.)
Thai / English UI (E8-13: `lib/i18n.ts` — `tr("<Thai text>", [args])`, Thai source text is the key, `en.ts`
holds the English; header toggle “ไทย | EN”, persisted in localStorage, re-mounts the app below the query cache;
years in BE for Thai, CE for English. **Rule for new UI text: write it in Thai inside `tr()` and add the English to
`src/i18n/en.ts`** — `src/i18n/i18n.test.ts` scans the source and fails on any Thai UI text outside `tr()`, a
missing/stale key, or mismatched `{n}` placeholders. `tr` not `t`: `t` is a transaction variable everywhere.
Server-generated text (engine reasons, XAI drivers, signals, anomalies, credit memo) stays Thai.)
Scenario comparison (E8-12: `GET /api/cases/{id}/comparison`, `services/comparison.py` — re-runs the engine in memory
with no / current / all-open-accepted Watchlist decisions via `load_inputs` + `run_engine` (split out of
`run_analysis`), sized with the same `ratios` functions; the “decided” column provably equals the stored analysis;
overview card `ScenarioComparison.tsx`.)
dStatement connector (E3-04: `connectors/dstatement.py` sandbox bank, HMAC-signed statement JSON, verified before
use; `services/dstatement.py` imports dates no uploaded statement covers — rows identical to the PDF parse, no bbox,
lineage shows the signed bank document — and *verifies* dates already covered: matched / differs / case_only /
bank_only → high-severity `bank_record_mismatch` anomaly with the rows; never changes a figure. Catches edited
PDFs, hidden transactions and OCR misreads. `POST /api/cases/{id}/dstatement`; HTTP stand-in at
`/sandbox/dstatement/v1/statements`.)
Utility/rent bill ingest (E2-14: PDF text layer, scanned PDF or JPEG/PNG photo → OCR with EXIF auto-rotate →
`parsers/bill.py` → `AltDataRecord(source="bill_upload")`; `services/bills.py` reconciles at each analysis: paid date
from a receipt or the matching statement debit, connector copy wins (conflicts flagged), no-payment-evidence is
asked about rather than counted unpaid, OCR-uncertain fields held until `POST /api/cases/{id}/bills/{rid}/review`;
lease end before maturity → the latest lease end on file caps the tenor at its remaining whole months (E6-06) via
`analysis.sizing_tenor()`, used by sizing, drivers, comparison, RM app, memo and LOS. Photos are served as an upright
PDF; `?original=true` gives the uploaded bytes.)
Ingest (auto-detect, passwords, SHA-256, encrypted at rest), e-Tax invoice ingest (E2-13: ETDA XML / PDF with
embedded XML / PDF text fallback → `Invoice(source="etax_upload", document_id)` → T1 matching; seller must be the
applicant; same invoice twice rejected; a PromptBiz copy of the same invoice wins so one sale never verifies two
receipts; XAdES signature only *detected*, not verified; scanned/photographed invoices go through OCR — an uncertain total is held out of T1 matching and blocks memo signing until a CA confirms/corrects it via `POST /api/cases/{id}/invoices/{iid}/review`), synthetic statement/ภ.พ.30 generator, parser with
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

Test counts at handoff: 236 backend, 22 frontend, 10 e2e — all green.

## Next
Every code item in `docs/BACKLOG.md` is done. Candidate follow-ups (not in the backlog):
- Bilingual server text: send message codes + params from the backend so engine reasons, XAI drivers, alt-data
  signals and anomaly titles translate too (the UI chrome already does — E8-13).
- XAdES signature verification for e-Tax XML (needs signxml/lxml + the Thai CA chain).
- Rehearse the demo script end to end and record the backup video (below).

Blocked on the team (not code): real-bank statement parsers need real sample statements (T-01); LINE integration
needs a LINE Official Account; backup demo video needs `npx playwright install ffmpeg` then `npm run e2e:record`.

## Not verified
i18n: server-generated narrative (tag reasons, XAI driver texts, alt-data signals, anomaly titles, warnings, the
credit memo PDF) is Thai only — making it bilingual needs message codes from the backend.
e-Tax: digital signatures are detected but not cryptographically verified (needs signxml/lxml + the Thai CA
chain); an unsigned upload is flagged as SME-provided evidence and still counts as T1 once it matches a real
receipt. PDF/A-3 conformance of
embedded-XML PDFs is not checked.
Bills: OCR of *new* photos needs the
live Azure provider (the sandbox only replays recorded responses for the generated samples).
dStatement: the sandbox signs with a shared HMAC key; a live adapter would verify the source bank's certificate.
Mismatches are flagged, not auto-corrected (the CA overrides/excludes the rows).
Dockerfile never built (Docker Desktop was off; re-checked 2026-09-28, still off). What *was* verified on 2026-09-28: the production server path the container runs (built SPA + `uvicorn app.main:app`) over real HTTP — SPA deep links, login, demo reset, a background job (202 in ~10 ms, live stage progress while polling, canonical 25.0M / DSCR 1.05 / 3.5M), reads during a running job without SQLite lock errors, audit chain intact. `requirements.txt` now pins Pillow and pypdfium2 (imported directly; previously only transitive). Azure OCR adapter never called live. Live LLM path only tested
with injected fakes (no API key) — the demo runs in template/cache mode.
