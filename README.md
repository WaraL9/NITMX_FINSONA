# Finsona AI

**Enterprise Credit Underwriting Intelligence Platform** — a copilot for bank credit analysts (CA) assessing Thai SME loans.

AI organizes the evidence, a deterministic engine does the math, the human decides, and every number traces back to a
highlighted line on the source document.

Finsona turns an SME's messy bank statements into a verified cash-flow picture and a safe loan size a CA can defend:
statements (PDF, scans, photos, or pulled straight from the bank) are parsed with pixel coordinates; a forensic engine
removes circular transfers, owner money and household spending; revenue is triangulated against PromptBiz e-invoices,
e-Tax invoices and ภ.พ.30 VAT filings; DSCR/DSR sizing proposes a safe limit and a structure instead of a rejection;
the CA judges what the evidence cannot prove; and the signed credit memo goes to the bank's loan system.

> Built for the NITMX/ITMX hackathon. The strategy it implements is in [`docs/ITMX.md`](docs/ITMX.md) (Thai); the
> backlog and the canonical demo numbers are in [`docs/BACKLOG.md`](docs/BACKLOG.md). The section
> [From the strategy to the product](#from-the-strategy-to-the-product) maps every promise in `ITMX.md` to what is built.

---

## Contents

- [Quick start](#quick-start)
- [How to use it](#how-to-use-it)
- [The demo in ten moments](#the-demo-in-ten-moments)
- [From the strategy to the product](#from-the-strategy-to-the-product)
- [What is live, what is sandboxed](#what-is-live-what-is-sandboxed)
- [Architecture](#architecture)
- [Commands](#commands)
- [Rules of the codebase](#rules-of-the-codebase)
- [Deploying](#deploying)

---

## Quick start

Requires **Python 3.11+** and **Node 20+** (Google Chrome for the browser tests).

```bash
npm run setup   # backend venv + deps, frontend deps, seed the demo database
npm run dev     # API on :8000, web app on http://localhost:5173
```

Sign in with a demo account (password **`finsona-demo`**), or click one of the demo buttons on the login page:

| User | Role | Lands on |
|---|---|---|
| `ca` | Credit analyst — analyses, decides, signs | Loan cases → case workbench |
| `rm` | Relationship manager — field app | `/rm` |
| `sme` | Business owner — self-service portal | `/sme` |
| `auditor` | Read-only auditor | Loan cases, audit log, governance |

The header has a **ไทย | EN** switch (the whole UI, including the engine's explanations, switches language), a
dark/light theme toggle, and — for the CA in demo mode — **↺ reset**, which restores the seeded demo in ~0.1 s.

No API keys are needed: external systems run as sandbox connectors, OCR replays recorded results, and AI text comes
from a cache or a template (every number is always the engine's). See
[What is live, what is sandboxed](#what-is-live-what-is-sandboxed).

---

## How to use it

### As a credit analyst (`ca`)

1. **Open a case** from *Loan cases*. Two are seeded:
   - **บริษัท กิตติ อินทีเรีย ดีไซน์** — the pitch case: 4 accounts (one password-protected PDF), 6 ภ.พ.30, PromptBiz invoices.
   - **บริษัท สมใจ ฟู้ดส์** — RM-sourced; one statement is a *scanned* image, so it has an OCR review queue.
2. **Documents & transactions** — drop files (they are recognised automatically):
   statement PDFs (password prompt if needed), scans and phone photos, ภ.พ.30, e-Tax invoices (ETDA XML, PDF with
   embedded XML, printed PDF or a photo), utility/rent bills. Or press **ดึงจากธนาคาร (dStatement)** to pull a signed
   statement straight from the account holder's bank — it imports dates you don't have and *verifies* the ones you
   uploaded (catching edited PDFs, hidden transactions and OCR misreads). Then press **วิเคราะห์ใหม่** — the analysis
   runs as a background job with a live stage-by-stage strip.
3. **Overview & cash flow** — the clean cash-flow waterfall (raw inflows → minus loops, owner money, unverified →
   verified revenue → minus operating costs), the **safe-limit simulator** (slider, DSCR/DSR, stress test, structure
   proposal), the **scenario comparison** (request vs safe limit vs after your decisions), the money-loop graph, the
   decision drivers (XAI), utility/rent behaviour and early warnings, customer concentration and anomalies.
   **Click any number** to see the exact transactions behind it; click a transaction to see the highlighted line
   on the original PDF.
4. **3-way reconciliation** — revenue by tier (T1 PromptBiz/e-Tax, T2 ภ.พ.30, T3 operational, T4 unverified) and the
   full transaction explorer; override a category with a professional reason.
5. **Watchlist** — inflows nothing can prove. For each one the system suggests what evidence would verify it; you
   **accept**, **exclude**, or **ask the RM** (one pinpoint question the RM or customer answers with a photo).
   Every decision needs a reason (≥ 10 characters) and goes to the hash-chained audit log; the figures update at once.
6. **OCR review** (scanned documents) — compare each uncertain value with the highlighted image and confirm or
   correct. Uncertain amounts are held out of every figure, and the memo cannot be signed until they are checked.
7. **Credit Memo** — the one-page memo with an evidence appendix; the AI drafts the wording, the engine supplies every
   number. Choose approve / approve with the safe-limit structure / decline, give your reason, **sign**, download the
   PDF, then **send to the LOS**.
8. **Audit log** — every upload, view, decision, override, review and export, chained with SHA-256; verify the chain
   or export CSV.

### As a relationship manager (`rm`)

The field app (`/rm`) lists your customers scored by readiness (ready / needs restructuring / needs data), gives
conversation starters and a gap diagnosis before a visit, a tablet-friendly sizing slider to show the customer, and
the CA's pinpoint questions — answer with a note and photos, or forward them to the customer.

### As a business owner (`sme`)

The portal (`/sme`) pre-qualifies a loan without touching the credit bureau, takes consent per purpose (PDPA),
lets you upload statements or let your bank send them (dStatement), shows your application's progress in real time,
and lets you answer the bank's questions with a phone photo — no need to resend the whole document set.

### As an auditor (`auditor`)

Read-only access to cases, the audit log (verify the chain, export CSV) and the **Governance** page, which runs live
checks: encryption at rest, audit-chain integrity, consent, PII masking before AI, authentication, AI and data-source mode.

---

## The demo in ten moments

What the browser test (`npm run e2e`) clicks, on the canonical Kitti case. The numbers are fixed by
[`docs/BACKLOG.md` §3](docs/BACKLOG.md) and asserted by tests.

| # | Moment | What you see |
|---|---|---|
| 1 | Pipeline | 10 real PDFs → 1,205 rows parsed, each with its page and bounding box |
| 2 | Circular transfers | 3.8M THB moved around the owner's own accounts, found and removed from revenue |
| 3 | Lineage | Click a Tier 1 figure → its rows sum exactly → click a row → the highlighted line on the PDF |
| 4 | Sizing | 5.0M requested → DSCR 1.05 (below 1.25) → *use safe limit* → 3.5M at DSCR 1.35 + 1.0M Trade Line |
| 5 | Judgement | Accept the 450k Watchlist receipt with a reason → safe limit 4.14M; the comparison shows +640,000 |
| 6 | Memo → LOS | Sign the structured approval → PDF with evidence appendix → LOS reference `LOS-YYYY-NNNNNN` |
| 7 | OCR review | Case 2: OCR read 2,954.19 where the scan shows 2,954.79 → correct it against the image |
| 8 | e-Tax invoice | Drop `etax_ETX-2512-0001.xml` → signature verified → re-analyse → the receipt becomes Tier 1 |
| 9 | Bill photo | Drop a sideways phone photo of a water bill → held for OCR review → confirm → corroborated |
| 10 | dStatement | Pull BBL from the bank → "uploaded file matches the bank 581/581" |

Also tested: the Thai/English switch, the Watchlist evidence hint sent to the RM in one click, a rent receipt whose
lease ends before the loan (the tenor is capped at 8 months and the safe limit falls), and a photographed e-Tax
invoice held until its OCR total is confirmed. Sample files are generated by `npm run seed` into `data/generated/`.

---

## From the strategy to the product

How each promise in [`docs/ITMX.md`](docs/ITMX.md) maps to the software. **Status:** ✅ built and tested ·
🟡 built against a sandbox (the live integration needs access we don't have) · ⬜ not software (strategy or business).

### 1. North Star and the four impact pillars (ITMX Part 1)

| Pillar | What ITMX says Finsona does | Where it is in the product | |
|---|---|---|---|
| **Access** | Judge SMEs on real cash flow and alternative data, not collateral or formal statements alone | Clean cash-flow engine, revenue tiers T1–T4, utility/rent behaviour, PromptPay velocity as evidence for cash businesses | ✅ |
| **Cost** | Cut the analyst's manual forensic work and the cost of a case | Auto-parsing with coordinates, loop detection, household filter, auto-drafted memo; the metrics page measures machine time per case | ✅ |
| **Speed** | Decisions within the business's cycle, not weeks | Whole case analysed in well under a second (background job with live progress); SME status tracker with SLA countdown | ✅ |
| **Inclusion** | Bring thin-file and cash-economy SMEs in, fairly | Structure a smaller safe loan + Trade Line instead of rejecting; cash-pattern detector treats site cash as a cost, not leakage; fairness check by business size (4/5 rule), no protected attributes | ✅ |

### 2. Root causes the product must fix (ITMX Part 2)

| Root cause in ITMX | How Finsona handles it | Where | |
|---|---|---|---|
| §2.1 Inflow ≠ revenue | Every inflow is classified and tiered; only T1–T3 count, T4 goes to the Watchlist | `engine/rules.py`, `engine/tiers.py`, 3-way reconciliation tab | ✅ |
| §2.2 Commingled funds (กงสี) | Owner/family transfers are capital, not revenue; school fees, personal car payments and family transfers are household, not business cost | `engine/rules.py`, *show separated household spending* on the waterfall | ✅ |
| §2.3 Circular flow / passing | Own-account transfers matched and chained into loops; pass-through money flagged | `engine/transfers.py`, loop graph, anomalies panel | ✅ |
| §2.4 Cash-economy friction | Regular cash withdrawals on material/wage days recognised as operating cost | `engine/cash_pattern.py`, drivers panel | ✅ |
| §1.3 Window dressing & fraud | Period-end unexplained inflows, round cash deposits, revenue spikes; tampered e-Tax signatures refused; uploaded PDFs verified against the bank's own record (dStatement) | `engine/anomalies.py`, `parsers/etax_signature.py`, `services/dstatement.py` | ✅ |
| §3.1 Defensive underwriting | Safe-limit + structure proposal instead of a flat rejection; every number defensible via lineage | Safe-limit simulator, scenario comparison, memo | ✅ |
| §3.2 The loop of infinite doubt | One pinpoint question per unexplained item, answered with a photo from the field; evidence hints say what to ask for | Watchlist → *Query RM*, RM app, SME portal | ✅ |
| §3.3 Manual forensic grunt work | Parsing, reconciliation, loop removal and the memo draft are automatic | The whole pipeline | ✅ |

### 3. Product positioning and design philosophy (ITMX Part 3)

| ITMX principle | Implementation | |
|---|---|---|
| §2.1 Strict human-in-the-loop | The system never decides; accept/exclude/override/sign each need a CA reason (≥ 10 chars) and are audit-logged | ✅ |
| §2.2 The Decision Package | Credit memo + evidence appendix (documents with SHA-256, external data used, every judgement with its reason), sent to the LOS as JSON | ✅ |
| §2.3 Deterministic math, not generative guesswork | All money is `Decimal`; the LLM writes words with `{{placeholders}}` and any digit it writes is rejected | ✅ |
| §2.4 Audit-ready pixel lineage | Every figure maps to a transaction filter whose rows sum to it exactly; every row to a page and bounding box; each view is logged | ✅ |
| §1.2 Stakeholders: CA, RM, SME, audit/risk | Four roles with their own screens and server-side access control | ✅ |

### 4. Multi-source triangulation (ITMX Part 3 §3)

| Source in ITMX | Implementation | |
|---|---|---|
| Multi-bank statements | PDF parser with coordinates, password-protected files, duplicate/overlap/coverage checks, OCR for scans and photos | ✅ (synthetic layout — see [limits](#what-is-live-what-is-sandboxed)) |
| dStatement | Signed statement pulled from the source bank with consent: imports missing dates, verifies uploaded ones | 🟡 sandbox bank |
| ภ.พ.30 VAT returns | Parser for the return; receipts within declared sales become Tier 2 | ✅ |
| PromptBiz e-Invoice network | Consent-gated connector; receipts matching an invoice (incl. withholding-tax net amounts) become Tier 1 | 🟡 sandbox connector |
| e-Tax invoices (in ITMX's PromptBiz data list) | ETDA XML, PDF with embedded XML, printed PDF or photo; XAdES signature verified; the applicant must be the seller | ✅ (sandbox CA until Thai CA roots are added) |
| Alternative data: utility, rent, PromptPay | Utility connector + uploaded bills (PDF/photo), payment matched to the statement; PromptPay velocity as Tier 3 | 🟡 connector sandboxed; bills ✅ |
| §3.2 Revenue verification tiers T1–T4 | Exactly the four tiers, with the reason shown on every transaction | ✅ |

### 5. Engineering (ITMX Part 4)

| ITMX design | Implementation | |
|---|---|---|
| §1 Circular transactions via a graph, avoiding O(n²) | Legs matched by bucketed binary search (O(n log n)), then loops found on a temporal directed graph of accounts, earliest-first and deterministic | ✅ `engine/transfers.py` |
| §2.1 Step 1 — enterprise OCR | Provider interface: Azure Document Intelligence adapter + a sandbox that replays recorded results; confidence gating to a human review queue; EXIF auto-rotation for photos | 🟡 Azure adapter untested (no key) |
| §2.2 Step 2 — LLM reasoning | One gateway (Claude): JSON-schema output, cache, PII masking, offline fallback; used for tagging help, memo wording and Watchlist evidence hints — never for numbers | ✅ (runs on templates/cache without a key) |
| §3.1 Deterministic math engine | Pure-Python engine over `Decimal`: waterfall, tiers, DSCR/DSR, PMT, safe limit, stress, structure | ✅ `engine/` |
| §3.2 Pixel-level lineage | Lineage drawer with the PDF page and the highlighted box; SHA-256 re-checked on view | ✅ |
| §4 End-to-end data flow | Upload → parse → engine → tiers → sizing → CA → memo → LOS, run as a background job with per-stage progress | ✅ |

### 6. Responsible lending and governance (ITMX Part 5)

| ITMX control | Implementation | |
|---|---|---|
| §1.1 Deterministic DSCR / DSR | `engine/ratios.py`, thresholds from a versioned credit policy (Credit policy page) | ✅ |
| §1.2 Dynamic safe-limit sizing | Safe limit at the target DSCR, stress sliders, term loan + Trade Line structure | ✅ |
| §2.1 Alt-data matrix — utilities | 12 months on time → liveness; 1–2 late > 30 days → 5–10% haircut; > 60 days → 25% + EWS | ✅ `engine/altdata.py` |
| §2.1 Alt-data matrix — rent | A lease ending before the loan caps the tenor at the lease's remaining months | ✅ `services/bills.py` |
| §2.1 Alt-data matrix — PromptPay velocity | Steady small PromptPay receipts count as Tier 3 | ✅ |
| §2.2 Early warning signals | EWS on the alt-data panel and in the memo | ✅ |
| §3.1 Explainable AI | Decision drivers: each factor's effect on the safe limit, computed with the same formula; memo narrative from engine facts | ✅ |
| §3.2 Bias mitigation | No gender, religion, ethnicity or hometown inputs; fairness by business size checked by the eval harness (4/5 rule) | ✅ |
| §4.2 Purpose-based PDPA consent | Consent per purpose (credit assessment, PromptBiz, utility, dStatement); revoking deletes fetched data | ✅ |
| §4.3 PII masking | Names, IDs, phones, emails, account numbers masked before anything reaches the LLM; what the AI saw is logged | ✅ |
| §4.4 Immutable audit log | Append-only, SHA-256 hash chain, tamper check, CSV export | ✅ |
| §4.1 FSI cloud (ISO 27001 / SOC 2, data in Thailand) | Single-container deployment with encrypted storage; the certification is the hosting provider's | ⬜ deployment choice (Governance page marks it as planned) |

### 7. User experience (ITMX Part 6)

| ITMX screen | In the app | |
|---|---|---|
| CA §1.1 Automated forensic cleansing canvas | Overview: waterfall, loops, drivers | ✅ |
| CA §1.2 Unverified inflow Watchlist & discretion hub | Watchlist tab with evidence hints and RM queries | ✅ |
| CA §1.3 Safe-limit sizing sandbox | Overview: simulator + scenario comparison | ✅ |
| CA §1.4 Pixel lineage & 1-page credit memo | Lineage drawer, Credit Memo tab (PDF + appendix) | ✅ |
| RM §2.1 Lead pool & opportunity scoring | `/rm` customer list with score and group | ✅ |
| RM §2.2 Conversation starters & gap diagnostic | `/rm` customer detail: *before meeting the customer* | ✅ |
| RM §2.3 Field pre-screening sandbox | `/rm` sizing slider | ✅ |
| RM §2.4 Pinpoint query & mobile clarification | Query cards with photo answers (in-app; LINE needs an Official Account) | ✅ / 🟡 LINE |
| SME §3.1 Pre-qualification & matching | `/sme` step 1 — estimate without a credit check | ✅ |
| SME §3.2 Flexible submission mode | Fast-track upload, RM-assisted, or dStatement | ✅ |
| SME §3.3 Real-time pipeline tracking | `/sme` status tracker with SLA countdown | ✅ |

### 8. Proof-of-concept KPIs (ITMX Part 7 §1.1)

Measured by the evaluation harness (`python -m app.eval.run`, 50 synthetic cases; results on the **Metrics** page).

| KPI in ITMX | Target | Measured | |
|---|---|---|---|
| Turnaround | CA effort −75–80% (15–20 h → 30–45 min) | Machine time ≈ 9 s per case; the manual baseline is ITMX's assumption | ✅ measured part |
| Extraction accuracy | Field-level > 98%, CER < 1.5% | 100% field accuracy, CER 0 on 3,601 rows — on our synthetic layout, **not** real bank statements | 🟡 needs real statements |
| Loop detection | False positives < 3% | 0% false positives, 100% recall on 50 cases (synthetic) | ✅ on synthetic data |
| CA adoption & NPS | > 85% adoption, positive NPS | Needs a pilot with real analysts | ⬜ |

The business model, pricing and defensibility sections of ITMX (Part 7 §2–3) are strategy, not software.

---

## What is live, what is sandboxed

Everything in the product is real, working code. Only **external systems** are mocked, as sandbox connectors with
the same interface a live adapter has, and every card shows a 🟢 Live / 🟡 Sandbox badge.

| External system | Today | To go live |
|---|---|---|
| PromptBiz e-invoices | Sandbox connector (consent token required) | NITMX API access |
| Utility & rent history | Sandbox connector (with a late-payment what-if switch) | MEA/PEA/waterworks data agreements |
| dStatement | Sandbox bank, HMAC-signed statements | Bank network access; verify the bank's certificate instead |
| LOS (loan system) | Sandbox endpoint, idempotent | The bank's LOS API |
| OCR | Replays recorded results for the demo scans/photos | `FINSONA_USE_LIVE_OCR=true` + Azure Document Intelligence key |
| LLM (Claude) | Cached responses, template wording without a key | `FINSONA_USE_LIVE_LLM=true` + an Anthropic API key |
| e-Tax signature trust | Generated sandbox CA | Put the Thai e-Tax CAs' certificates in [`data/trust/`](data/trust/README.md) |

Known limits: the statement parser reads our synthetic bank layout — real banks need real sample statements; the
credit memo and AI narrative are Thai only (a Thai bank's document). Details in [`docs/HANDOFF.md`](docs/HANDOFF.md).

---

## Architecture

```
PDF / scan / photo / XML / dStatement
        │  ingest: detect type, SHA-256, decrypt, encrypt at rest
        ▼
   parsers (+ OCR)  ──►  transactions with page + bounding box
        │
        ▼
   engine (pure, Decimal)
     loops ─► classify (owner, household, debt) ─► tiers (PromptBiz/e-Tax, ภ.พ.30, context) ─► cash flow
        │                                     ▲
        │          connectors (PromptBiz, utility, dStatement)  — consent-gated
        ▼
   sizing: DSCR/DSR, safe limit, stress, structure, alt-data haircut, tenor cap, drivers
        │
        ▼
   CA workbench ─► Watchlist decisions / overrides / OCR review (audit-logged)
        │
        ▼
   credit memo PDF + evidence appendix ─► LOS
```

- **Backend** — FastAPI, SQLAlchemy 2 (SQLite), pydantic 2, pdfplumber/pypdf, ReportLab, signxml; Claude via the
  Anthropic SDK behind one gateway.
- **Frontend** — React 19, Vite, Tailwind v4, TanStack Query, typed client generated from the OpenAPI schema;
  Thai/English with a completeness test.
- **Tests** — pytest (engine, parsers, API, canonical numbers), Vitest, Playwright end-to-end in real Chrome.

```
backend/
  app/engine/      the deterministic engine (loops, rules, tiers, ratios, alt data, drivers)
  app/parsers/     statements, ภ.พ.30, e-Tax (XML/PDF/OCR + signatures), bills, dStatement
  app/connectors/  PromptBiz, utility, dStatement, LOS (sandbox + interfaces)
  app/services/    ingest, analysis, jobs, memo, audit, consent, OCR review, comparison…
  app/ai/          LLM gateway, PII masking, tagging, memo narrative, evidence hints
  app/api/         HTTP routes
  app/synth/       synthetic statements, tax documents, invoices, bills, sandbox CA
  tests/           pytest
frontend/src/
  pages/           case list, workbench, RM app, SME portal, policy, metrics, governance
  components/      workbench panels, lineage drawer, documents, UI primitives
  i18n/            English dictionaries (UI and server text) + completeness test
e2e/               Playwright demo tests
data/              scenarios, fonts, LLM cache, trust store (generated files are git-ignored)
docs/              ITMX strategy, backlog, handoff
```

---

## Commands

| Command | What it does |
|---|---|
| `npm run setup` | Backend venv + dependencies, frontend dependencies, seed |
| `npm run dev` | Backend (auto-reload) + frontend together |
| `npm run seed` | Rebuild the demo data and database; snapshot it for instant resets |
| `npm run demo:reset` | Restore the seeded demo (same as ↺ in the header) |
| `npm test` | Backend (pytest) + frontend (Vitest) tests |
| `npm run test:api` / `npm run test:web` | One side only |
| `npm run e2e` | The browser tests of the demo (uses installed Chrome; starts its own servers) |
| `npm run e2e:record` | The same, headed and slowed, saving a video — the backup recording (`npx playwright install ffmpeg` once) |
| `npm run typecheck` | TypeScript check |
| `npm run build` | Build the web app |
| `npm run gen:api` | Regenerate the frontend API types from the backend schema |
| `npm start` | Production: build and serve app + API from one process on http://127.0.0.1:8000 (`start:lan` for other devices) |
| `python -m app.eval.run` (in `backend/`) | Evaluation harness behind the Metrics page |

---

## Rules of the codebase

- **Money is never a float.** `Decimal` everywhere, stored as integer satang, sent as decimal strings; the frontend
  only formats.
- **The LLM never produces numbers.** It tags and writes prose with placeholders; a digit outside a placeholder
  rejects the draft.
- **Lineage invariant.** Every figure maps to a transaction filter whose rows sum to it exactly (tested).
- **Human in the loop.** Every CA decision needs a reason and goes to the hash-chained audit log.
- **Bilingual.** UI text is written in Thai inside `tr("…")` with English in `frontend/src/i18n/en.ts`; server text a
  user sees is marked `th("…")` with English in `frontend/src/i18n/en_server.json`. Tests fail on anything missing.
- **Canonical numbers.** The Kitti case figures in `docs/BACKLOG.md` §3 are asserted by tests; don't change
  `data/scenario_kitti.yaml`.

---

## Deploying

```sh
docker build -t finsona .
docker run -p 8000:8000 -v finsona-data:/data finsona   # http://localhost:8000
```

Database, encrypted files and generated keys live in the `/data` volume. Supply `FINSONA_STORAGE_KEY` /
`FINSONA_SECRET_KEY` for your own keys and `FINSONA_DEMO_MODE=false` to hide demo logins and reset. Without Docker,
`npm start` serves the same thing from one process. Analysis jobs also work with several server workers.
