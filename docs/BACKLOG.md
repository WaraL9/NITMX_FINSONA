# Finsona AI — Product Backlog (Super Sprint)

> Source of truth: `ITMX.md`. This backlog turns the strategy docs into buildable, testable items.
> Scope: **full product, nothing cut**. Priority decides *order*, not *whether*.

---

## 0. Working agreements

### Assumptions (change here if wrong)
- **Stack:** Python 3.11 + FastAPI + SQLite (SQLAlchemy) backend · React + TypeScript + Vite + Tailwind + shadcn/ui frontend · pdf.js for PDF rendering · React Flow for graphs · Recharts for charts.
- **AI services:** one OCR provider (Azure Document Intelligence or Typhoon OCR) + one LLM API. Every AI call has a **cached fallback** so the demo works offline.
- **Engineering team:** 1 engineer (+ Claude Code). Non-engineering teammates own the `T-` items in §5.
- **External parties we cannot access** (PromptBiz API, dStatement, utility APIs, core banking/LOS) are built as **Sandbox Connectors** behind the same interface as a live connector, and labelled 🟡 Sandbox in the UI. Everything else is 🟢 Live.

### Priority levels
| Level | Meaning |
|---|---|
| **P0** | Demo-critical. The pitch fails without it. |
| **P1** | Core product value. Judges will ask about it. |
| **P2** | Completes the product vision (RM/SME/governance depth). |

### Story points
Fibonacci (1, 2, 3, 5, 8, 13). 1 pt ≈ roughly 1 focused hour for the solo engineer with Claude Code. Use it for relative sizing, not as a promise.

### Definition of Ready
- Acceptance criteria written · dependencies done or stubbed · test data available.

### Definition of Done
- Acceptance criteria met · engine logic has unit tests · works on the canonical demo case (§3) · no console errors · committed to `main` · demo path still runs end to end.

---

## 1. Sprint goal

> **"A credit analyst uploads a real multi-bank SME case and, in under 15 minutes, gets a cleaned cash flow, verified revenue tiers, a safe loan size and an audit-ready 1-page memo, where every number is traceable to a pixel on the source PDF and every judgement is made and logged by a human."**

---

## 2. Increments inside the super sprint

Each increment ends with a **working, demoable product**. Do not start increment N+1 while N's demo path is broken.

| Inc | Goal | Items |
|---|---|---|
| **I0** | Skeleton runs | E0-01..E0-05, E1-01 |
| **I1** | Real PDF → transactions with bounding boxes | E2-01..E2-05, E1-02 |
| **I2** | Engine: clean cash flow + tiers + DSCR | E4-01..E4-04, E5-01..E5-04, E6-01..E6-04, E3-01..E3-03 |
| **I3** | CA Workbench demo path (P0 UI) | E8-01..E8-06, E9-01..E9-04, E10-01..E10-03 |
| **I4** | Memo, AI layer, audit integrity | E11-01..E11-03, E7-01..E7-04, E9-05, E6-05..E6-07 |
| **I5** | RM + SME apps | E12-*, E13-* |
| **I6** | Governance, evaluation, remaining P1/P2 | E14-*, E15-*, remaining items |
| **I7** | Hardening & demo readiness | E16-* (feature freeze starts here) |

---

## 3. Canonical demo case: บริษัท กิตติ อินทีเรีย ดีไซน์ จำกัด

All numbers below are **internally consistent** and verified. The engine must reproduce them exactly from the seed data. The deck must use these numbers.

**Profile:** interior fit-out contractor, 7 years old · 4 accounts across 3 banks (BBL, KBANK, SCB + director's personal account) · 6-month window (Dec 2025 – May 2026).
**Request:** 5,000,000 THB working-capital loan · 12-month amortizing · 7.00% p.a.
**Bank policy:** minimum DSCR **1.25** (red below) · recommended target DSCR **1.35**.

### Revenue waterfall (6 months)
| Line | THB |
|---|---|
| Gross raw inflow (4 accounts) | 32,000,000 |
| − Own-account transfer loops | −3,800,000 |
| − Owner/family inflows (capital injections, family transfers in) | −1,200,000 |
| − Unverified inflows (held on Watchlist, 3 items incl. 450,000) | −2,000,000 |
| **= Verified operating revenue** | **25,000,000** |

### Revenue tiers (of 25,000,000)
| Tier | THB | Share |
|---|---|---|
| T1 Golden (matched to PromptBiz / e-Tax invoice) | 15,000,000 | 60% |
| T2 Tax-verified (within ภ.พ.30 declared sales) | 8,000,000 | 32% |
| T3 Operational (context-supported) | 2,000,000 | 8% |
| T4 Unverified (Watchlist, **excluded**) | 2,000,000 | — |

### Cash flow & debt
| Line | Value |
|---|---|
| Business operating costs (COGS + OpEx, 6 mo) | 21,320,416 |
| Household expenses (school fees, car loan — excluded as owner drawings) | 900,000 |
| **Clean operating cash flow (6 mo)** | **3,679,584** → **613,264 / month** |
| Existing debt service | 151,426 / month |

### Sizing (PMT factor, 12 mo @ 7% = 0.086527)
| Scenario | New payment / mo | DSCR |
|---|---|---|
| Request 5,000,000 | 432,635 | **1.05** 🔴 |
| Safe limit 3,500,000 (at target 1.35) | 302,844 | **1.35** 🟢 |
| Max at minimum 1.25 | ≈ 3,920,000 | 1.25 |
| After CA accepts the 450,000 Watchlist item (CFO +75,000/mo) | safe limit ≈ **4,140,000** at 1.35 | — |

**Structural suggestion shown in UI:** approve 3.5M term + 1.0M PromptBiz-linked Trade Line.

### Transfer loops to plant (3.8M total, sum of loop legs netted)
- Loop A (2-hop): BBL → KBANK → BBL, 500,000 → 495,000 within 24h.
- Loop B (3-hop): BBL → KBANK → Director → BBL, 500,000 → 495,000 → 490,000 within 48h (total 1,485,000).
- Remaining loops sized so the netted total = 3,800,000.

### Watchlist items (2,000,000)
1. 08/03/2026 · บจก. เอ บิลด์ · **450,000** · memo "งวดที่ 1 งานตกแต่งคลินิก" · no PromptBiz invoice → RM uploads contract photo.
2. Two further items summing to 1,550,000 (one looks like a deposit, one ambiguous).

> The 450,000 row must be on the **same date (08/03/2026)** in the Watchlist, the PDF highlight, and the memo.

---

## 4. Product backlog

### E0 — Foundation & DevEx
| ID | Item | Acceptance criteria | Pts | Pri | Deps |
|---|---|---|---|---|---|
| E0-01 | Monorepo scaffold | `/backend` (FastAPI) + `/frontend` (Vite React TS) + `/data` + `/docs`; one command starts both (`make dev` or script); README with setup steps | 3 | P0 | — |
| E0-02 | Domain model & DB | SQLite + SQLAlchemy models: Case, Account, Document, Page, Transaction (with bbox, confidence, page_id), Invoice, TaxFiling, AltDataRecord, Tag, Tier, WatchlistItem, Decision, AuditEntry, User; Alembic or create-all | 5 | P0 | E0-01 |
| E0-03 | API contract | OpenAPI schema for cases, uploads, analysis, watchlist, sizing, lineage, memo; typed client generated for frontend | 3 | P0 | E0-02 |
| E0-04 | Design system | Tailwind tokens for the Clean White palette in ITMX.md (Slate/Emerald/Amber/Navy/Red), Thai-capable font (IBM Plex Sans Thai / Noto Sans Thai), base components (Card, Badge, Button, Table, Modal, Toggle, Slider) | 3 | P0 | E0-01 |
| E0-05 | Test harness | pytest for engine with fixtures; Vitest for frontend utils; CI-able `make test` | 2 | P0 | E0-01 |
| E0-06 | Config & feature flags | `.env` for provider keys; flags `USE_LIVE_OCR`, `USE_LIVE_LLM`, `CONNECTOR_MODE=sandbox/live`; cached-fallback switch | 2 | P1 | E0-01 |
| E0-07 | Background jobs | Analysis pipeline runs as a job with status polling (FastAPI BackgroundTasks or RQ); progress events per stage | 3 | P1 | E0-02 |
| E0-08 | Money & date utilities | Decimal-only money type (no floats), THB formatting, Thai/Buddhist-era date parsing (พ.ศ. → ค.ศ.) | 2 | P0 | E0-01 |

### E1 — Demo data & scenario
| ID | Item | Acceptance criteria | Pts | Pri | Deps |
|---|---|---|---|---|---|
| E1-01 | Scenario spec as code | `data/scenario_kitti.yaml` encodes §3 (accounts, loops, tiers, costs, debt, watchlist) | 2 | P0 | — |
| E1-02 | Synthetic statement generator | Script generates ~1,500 transactions across 4 accounts matching §3 exactly; outputs JSON + bank-styled **PDFs** (ReportLab) with known row bounding boxes | 8 | P0 | E1-01, E0-08 |
| E1-03 | Synthetic PromptBiz / e-Tax invoices | Generate invoice records (JSON + e-Tax-style XML) that match exactly 15.0M of inflows | 3 | P0 | E1-02 |
| E1-04 | Synthetic ภ.พ.30 | 6 monthly filings (PDF + JSON) whose sales cover the T2 portion | 2 | P0 | E1-02 |
| E1-05 | Synthetic alt data | 12 months utility + rent records; base case = clean; scenario toggle = 2 late electricity payments | 2 | P1 | E1-01 |
| E1-06 | Scenario validator | Test asserts engine output == §3 numbers to the baht (waterfall, tiers, DSCR 1.05/1.35, safe limit 3.5M) | 3 | P0 | E1-02, E6-03 |
| E1-07 | Second demo case | A "cash-intensive recycling plant" case (Mon/Thu cash withdrawals) to show the cash-COGS classifier | 3 | P2 | E1-02 |
| E1-08 | Real-loop case | Import the team's real statements containing the real cross-bank loop (T-02) | 2 | P1 | E2-02, T-02 |

### E2 — Document ingestion & extraction
| ID | Item | Acceptance criteria | Pts | Pri | Deps |
|---|---|---|---|---|---|
| E2-01 | Upload service | Multi-file upload (PDF/JPG/PNG/XML); stores original; computes **SHA-256**; creates Document + Page records | 3 | P0 | E0-02 |
| E2-02 | Digital PDF statement parser — Bank 1 | pdfplumber/PyMuPDF extracts rows with date, desc, debit, credit, balance, counterparty (if present) **and bbox per row**; balance-continuity check passes | 8 | P0 | E2-01, E0-08 |
| E2-03 | Password-protected PDFs | Password field on upload; decrypt in memory; never store password | 2 | P0 | E2-01 |
| E2-04 | Parser plug-in registry | Auto-detect bank from header text; route to correct parser; unknown → OCR path | 3 | P0 | E2-02 |
| E2-05 | Normalized schema | All parsers output one `Transaction` schema; Buddhist-era dates normalized; amounts as Decimal | 2 | P0 | E2-02 |
| E2-06 | Parser — Bank 2 | Same AC as E2-02 for a second bank | 5 | P1 | E2-04 |
| E2-07 | Parser — Bank 3 | Same AC as E2-02 for a third bank | 5 | P2 | E2-04 |
| E2-08 | OCR path for scans/photos | Scanned PDF or photo → OCR provider → rows with bbox + confidence; deskew/rotate pre-processing | 8 | P1 | E2-04, E0-06 |
| E2-09 | Confidence gating | Any row/cell < 0.50 confidence → **Human Review Queue**, excluded from math until confirmed | 3 | P1 | E2-08 |
| E2-10 | Human Review Queue UI | Shows cropped image of the low-confidence row next to editable extracted values; confirm/correct; correction is audit-logged | 5 | P1 | E2-09, E9-05 |
| E2-11 | Statement integrity checks | Opening + credits − debits = closing per page/period; gaps in dates flagged; duplicate pages detected by hash | 3 | P1 | E2-05 |
| E2-12 | ภ.พ.30 parser | Extract month, sales, purchases, VAT from ภ.พ.30 PDF; manual-entry form fallback | 5 | P0 | E2-01 |
| E2-13 | e-Tax invoice ingest | Parse e-Tax invoice XML (ETDA standard) + PDF fallback: invoice no, date, buyer, seller, amount | 5 | P1 | E2-01 |
| E2-14 | Utility/rent bill ingest | Upload bills (PDF/photo) → due date, paid date, amount; late-payment detection | 5 | P2 | E2-08 |
| E2-15 | Account ownership mapping | CA/SME marks which uploaded accounts belong to the company / director / family; used by netting and commingling | 2 | P0 | E2-05 |

### E3 — Connectors (Live / Sandbox)
| ID | Item | Acceptance criteria | Pts | Pri | Deps |
|---|---|---|---|---|---|
| E3-01 | Connector interface | `InvoiceSource`, `StatementSource`, `TaxSource`, `AltDataSource` interfaces; each implementation declares `mode: live/sandbox` | 2 | P0 | E0-02 |
| E3-02 | PromptBiz Sandbox Connector | Mock REST server (separate FastAPI router) serving e-Invoice + settlement status for a business ID; realistic latency; consent token required | 5 | P0 | E3-01, E1-03 |
| E3-03 | Live/Sandbox badge | Every data card shows 🟢 Live / 🟡 Sandbox with source name | 1 | P0 | E3-01, E0-04 |
| E3-04 | dStatement Sandbox Connector | Mock API returns statement JSON for consented accounts; same schema as parsed PDFs | 3 | P2 | E3-01 |
| E3-05 | Utility Sandbox Connector | Mock MEA/PEA/water payment history API | 2 | P2 | E3-01 |
| E3-06 | LOS / Core-banking export | Export decision package as JSON to a mock LOS endpoint; show "Synced to LOS" receipt | 3 | P2 | E11-01 |
| E3-07 | LINE Messaging integration (Live) | Real LINE Official Account push for RM/SME pinpoint queries; webhook receives photo reply | 5 | P2 | E12-04 |

### E4 — Forensic engine
| ID | Item | Acceptance criteria | Pts | Pri | Deps |
|---|---|---|---|---|---|
| E4-01 | Transfer matcher (2-hop) | Matches debit in own account A to credit in own account B: amount within tolerance (≤ 1% or fee), within Δt (default 72h); O(n log n) via sort + hash buckets; unit tests incl. fee loss | 5 | P0 | E2-05, E2-15 |
| E4-02 | Multi-hop loop detection | Builds temporal directed graph of matched legs; finds cycles returning to origin group within Δt with decaying amounts (3–4 hops); detects Loop B in §3 | 8 | P0 | E4-01 |
| E4-03 | Netting & explanation | Loop volumes removed from revenue exactly once (no double subtraction); each netted txn links to its loop ID | 3 | P0 | E4-02 |
| E4-04 | Owner/family inflow filter | Inflows from director/family accounts or same-surname counterparties tagged `owner_injection`; excluded from revenue; toggle to include | 3 | P0 | E2-15 |
| E4-05 | Household expense filter | Outflows recognised as school fees, personal car loan, family transfers → `household`; excluded from OpEx as owner drawings | 3 | P1 | E4-04 |
| E4-06 | Cash-COGS classifier | Detects periodic cash withdrawals (weekday pattern, regular amounts) correlated with production cycle → `verified_cash_cogs` with evidence text | 5 | P1 | E2-05 |
| E4-07 | Rule engine for tags | Keyword/regex rules (Thai + English) for salary, utilities, rent, loan repayment, tax, card settlement; rules editable in YAML | 3 | P0 | E2-05 |
| E4-08 | Existing-debt detector | Identifies recurring loan repayments to other banks → existing debt service figure | 3 | P0 | E4-07 |
| E4-09 | Anomaly flags | Round-number spikes, end-of-month inflow bursts before application date, same-day in/out pairs from third parties | 3 | P2 | E2-05 |

### E5 — Triangulation & revenue tiers
| ID | Item | Acceptance criteria | Pts | Pri | Deps |
|---|---|---|---|---|---|
| E5-01 | Invoice ↔ inflow matcher | Match inflows to PromptBiz/e-Tax invoices by amount (± fees/WHT 1–3%), counterparty similarity, date window; one-to-one and one-to-many (partial payments) | 8 | P0 | E3-02, E4-03 |
| E5-02 | ภ.พ.30 reconciliation | Monthly: unmatched inflows up to declared sales → T2; excess flagged "above declared sales" | 5 | P0 | E2-12, E5-01 |
| E5-03 | Operational tier rules | Remaining inflows supported by context (recurring customer, PromptPay QR velocity, consistent with production cycle) → T3 | 3 | P0 | E5-02 |
| E5-04 | Unverified → Watchlist | Everything else → T4 + WatchlistItem, sorted by amount × suspicion score | 2 | P0 | E5-03 |
| E5-05 | Tier explanation | Each inflow shows *why* it got its tier (matched invoice no., filing month, rule fired) | 3 | P1 | E5-04 |
| E5-06 | Customer concentration | Share of revenue from top-1/top-5 customers; warning above threshold | 2 | P2 | E5-01 |

### E6 — Risk math engine (deterministic)
| ID | Item | Acceptance criteria | Pts | Pri | Deps |
|---|---|---|---|---|---|
| E6-01 | Clean cash-flow calculator | Revenue (T1–T3) − business costs = clean operating cash flow; monthly + period; Decimal math; unit-tested | 3 | P0 | E5-04, E4-05 |
| E6-02 | Loan math library | PMT, inverse PMT (principal from payment), configurable rate/tenor; tested against spreadsheet values | 2 | P0 | E0-08 |
| E6-03 | DSCR & DSR | DSCR = CFO / total debt service; DSR per ITMX definition; reproduces 1.05 and 1.35 from §3 | 2 | P0 | E6-01, E6-02, E4-08 |
| E6-04 | Safe-limit solver | Given target DSCR → max new payment → max principal; returns 3.5M at 1.35 for §3 | 3 | P0 | E6-03 |
| E6-05 | Stress test | Sliders: costs +x%, revenue −y%, rate +z bp → recompute DSCR & safe limit live | 3 | P1 | E6-04 |
| E6-06 | Alt-data haircut engine | Rules from ITMX §2.1 matrix: late utility 1–2× in 6 mo → 5–10% CFO haircut; >60 days / disconnection notice → 25% + EWS; rent expiry → cap tenor | 5 | P1 | E2-14 or E3-05, E6-01 |
| E6-07 | Structure suggestion | When request > safe limit: propose term loan at safe limit + Trade Line sized on T1 invoice flow (1.0M in §3) | 3 | P1 | E6-04, E5-01 |
| E6-08 | Policy config | Min DSCR, target DSCR, max DSR, haircut table editable per bank product (YAML/admin page) | 2 | P1 | E6-04 |
| E6-09 | Calculation trace | Every output number carries a formula trace (inputs → formula → result) for the XAI panel and memo | 3 | P1 | E6-03 |

### E7 — AI layer
| ID | Item | Acceptance criteria | Pts | Pri | Deps |
|---|---|---|---|---|---|
| E7-01 | LLM gateway | One client with timeout, retry, JSON-schema output validation, response cache keyed by input hash, offline fallback | 3 | P1 | E0-06 |
| E7-02 | LLM transaction tagging | For rows the rules can't tag: LLM returns `{tag, confidence, rationale}` only — **never numbers**; low-confidence → rules default | 5 | P1 | E7-01, E4-07 |
| E7-03 | Cash-pattern explanation | LLM drafts Thai explanation for cash-COGS pattern using facts provided by E4-06 | 2 | P1 | E7-01, E4-06 |
| E7-04 | Narrative risk synthesis | Thai memo narrative generated from the engine's JSON facts; numbers **injected by template**, not generated; validator rejects any number not present in facts | 5 | P1 | E7-01, E6-09 |
| E7-05 | Watchlist hint | For each Watchlist item, LLM suggests what evidence would verify it (e.g. "contract for clinic fit-out, instalment 1") | 2 | P2 | E7-01, E5-04 |
| E7-06 | Decision attribution (XAI) | Positive drivers / risk factors list with each factor's impact on safe limit (THB and %), computed deterministically by ablation | 5 | P1 | E6-09 |
| E7-07 | Actionable feedback | When below policy: list concrete fixes with computed effect ("link PromptBiz e-Invoices → +X THB safe limit") | 3 | P2 | E7-06 |

### E8 — CA Workbench UI
| ID | Item | Acceptance criteria | Pts | Pri | Deps |
|---|---|---|---|---|---|
| E8-01 | Case list dashboard | Table of cases: company, industry, amount requested, status, SLA timer, source (portal/RM) | 3 | P0 | E0-03 |
| E8-02 | Case header | Company, industry badge, business age, amount, purpose, amber "Human Action Required" status | 2 | P0 | E8-01 |
| E8-03 | Analysis pipeline progress | Stage stepper (Upload → Extract → Structure → Loops → Tiers → Sizing) with live progress from E0-07 | 3 | P0 | E0-07 |
| E8-04 | Cash-flow waterfall | Waterfall chart + cards matching §3; family toggle; every number clickable (→ lineage) | 5 | P0 | E6-01 |
| E8-05 | Revenue tier cards | T1–T4 cards with amounts, share, PromptBiz Certified badge, Live/Sandbox badge, "Open Watchlist (3)" | 3 | P0 | E5-04 |
| E8-06 | Safe-limit sandbox | Slider 1.0–5.0M; DSCR/DSR live; red/green vs policy; marker at safe limit; structure suggestion box | 5 | P0 | E6-04 |
| E8-07 | Money-loop graph modal | React Flow: accounts as nodes, loop legs as animated red edges with amount + timestamp; click edge → lineage | 5 | P1 | E4-02 |
| E8-08 | Transactions explorer | Filterable table of all transactions with tags, tier, loop ID, confidence; bulk re-tag with reason | 5 | P1 | E4-07 |
| E8-09 | Stress-test panel | UI for E6-05 sliders with before/after comparison | 3 | P1 | E6-05 |
| E8-10 | Alt-data & EWS panel | Utility/rent timeline, late payments highlighted, haircut applied and why | 3 | P1 | E6-06 |
| E8-11 | XAI panel | Drivers/risks list from E7-06 with impact bars | 3 | P1 | E7-06 |
| E8-12 | Case comparison | Side-by-side of two scenarios (request vs safe limit vs after Watchlist decisions) | 3 | P2 | E8-06 |
| E8-13 | Thai / English toggle | UI strings in both languages | 3 | P2 | E0-04 |

### E9 — Human-in-the-loop & audit
| ID | Item | Acceptance criteria | Pts | Pri | Deps |
|---|---|---|---|---|---|
| E9-01 | Watchlist table | Items sorted by amount/suspicion; system note (e.g. keyword found, no invoice); status chip | 3 | P0 | E5-04 |
| E9-02 | CA actions | Accept as Operating / Keep Non-Operating / Query RM buttons; **reason required**; state machine enforced server-side | 3 | P0 | E9-01 |
| E9-03 | Live recalculation | Accepting an item moves it into T3, updates waterfall, DSCR and safe limit (450k → safe limit ≈ 4.14M per §3) within 1s | 3 | P0 | E9-02, E6-04 |
| E9-04 | Override any tag | CA can override any system tag/tier with reason; override shown with "CA override" marker | 3 | P1 | E9-02 |
| E9-05 | Audit log (hash chain) | Append-only AuditEntry: timestamp, user, IP, action, before/after, reason, `prev_hash`, `hash`; logs uploads, extractions, lineage views, decisions, exports | 3 | P0 | E0-02 |
| E9-06 | Audit integrity check | "Verify audit trail" button recomputes the chain; demo: tamper a row in DB → verification fails at that entry | 2 | P1 | E9-05 |
| E9-07 | Audit log viewer | Timeline panel per case, filter by user/action, export CSV | 3 | P1 | E9-05 |
| E9-08 | Decision sign-off | CA final recommendation (approve / approve at safe limit / decline) with reason; locks case; version snapshot stored | 3 | P1 | E9-02 |

### E10 — Pixel lineage
| ID | Item | Acceptance criteria | Pts | Pri | Deps |
|---|---|---|---|---|---|
| E10-01 | Lineage model | Every derived number stores the list of source transaction IDs; every transaction stores doc hash, page, bbox, extractor version | 3 | P0 | E2-02, E6-09 |
| E10-02 | Split-screen PDF viewer | pdf.js renders original page; orange bbox overlay drawn from stored coordinates; zoom and page nav | 5 | P0 | E10-01 |
| E10-03 | Click-to-trace | Clicking any number opens the viewer; aggregated numbers show a list of contributing rows, each clickable | 3 | P0 | E10-02 |
| E10-04 | Lineage metadata footer | Shows file name, SHA-256 verified ✔ (recomputed), bbox, confidence, extractor version | 2 | P0 | E10-02 |
| E10-05 | Evidence attachments | RM/SME uploaded photos (contracts, site photos) viewable in the same panel next to the txn | 2 | P1 | E12-05 |

### E11 — Credit memo & export
| ID | Item | Acceptance criteria | Pts | Pri | Deps |
|---|---|---|---|---|---|
| E11-01 | Decision package JSON | Machine-readable package: waterfall, tiers, ratios, sizing, decisions, audit hash head | 2 | P0 | E6-04, E9-05 |
| E11-02 | 1-page memo view | A4 print-styled page: waterfall, tiers, sizing, drivers/risks, CA reasoning, "Prepared by Finsona AI Engine · Verified & approved with CA discretion by …" | 5 | P0 | E11-01 |
| E11-03 | PDF export | Server-side PDF (WeasyPrint/Playwright) of the memo; numbers carry lineage link IDs; file hash recorded in audit log | 3 | P0 | E11-02 |
| E11-04 | Memo narrative | Embed E7-04 narrative with "AI-drafted, CA-reviewed" label; CA can edit before export | 2 | P1 | E7-04, E11-02 |
| E11-05 | Evidence appendix | Optional appendix with thumbnails of highlighted source rows for each key number | 3 | P2 | E10-02, E11-03 |

### E12 — RM field assistant (mobile web)
| ID | Item | Acceptance criteria | Pts | Pri | Deps |
|---|---|---|---|---|---|
| E12-01 | RM lead pool | Mobile list of incoming cases with Opportunity Score and group (ready / needs restructuring / needs more data) | 3 | P2 | E8-01, E6-04 |
| E12-02 | Opportunity scoring | Deterministic score from data completeness, DSCR headroom, T1 share; explanation shown | 3 | P2 | E12-01 |
| E12-03 | Gap diagnostic & conversation starters | Per case: missing docs, DSCR tension, "linking PromptBiz could unlock +X" (from E7-07) | 3 | P2 | E7-07 |
| E12-04 | Pinpoint query inbox | CA "Query RM" creates a task tied to one transaction; RM sees it on mobile with the highlighted row | 3 | P1 | E9-02 |
| E12-05 | Evidence capture & reply | RM uses phone camera to attach photos + note; reply appears on CA Watchlist item in real time (polling/WebSocket) | 5 | P1 | E12-04 |
| E12-06 | Field safe-limit sandbox | Tablet-friendly slider for RM to show the customer | 2 | P2 | E8-06 |

### E13 — SME portal
| ID | Item | Acceptance criteria | Pts | Pri | Deps |
|---|---|---|---|---|---|
| E13-01 | Pre-qualification form | 4 inputs (amount, industry, monthly revenue, expected rate) → High / Conditional / Mismatch with reasons | 3 | P2 | E6-04 |
| E13-02 | Safe-borrowing suggestion | On Mismatch, show indicative safe limit instead of rejection | 2 | P2 | E13-01 |
| E13-03 | Consent flow (PDPA) | Purpose-based consent screens (credit assessment, PromptBiz data, utility data); consent records stored with timestamp and version | 3 | P1 | E14-02 |
| E13-04 | Submission modes | Fast-Track (upload statements + ภ.พ.30 + connect PromptBiz sandbox) or RM-Assisted (contact request) | 3 | P2 | E2-01, E3-02 |
| E13-05 | Pipeline tracker | 5-stage status bar with SLA countdown, driven by real case state | 3 | P2 | E8-01 |
| E13-06 | SME clarification reply | SME receives a pinpoint question (web or LINE) and replies with a photo | 3 | P2 | E12-05, E3-07 |

### E14 — Governance, security & privacy
| ID | Item | Acceptance criteria | Pts | Pri | Deps |
|---|---|---|---|---|---|
| E14-01 | Users & roles | Simple login (seeded users) with roles CA / RM / SME / Auditor; route + API guards | 3 | P1 | E0-02 |
| E14-02 | Consent registry | Consent records checked before any connector call or analysis; missing consent blocks with clear message | 3 | P1 | E3-01 |
| E14-03 | PII masking | Thai national ID (13-digit, checksum), phone, personal addresses masked before LLM calls; account numbers tokenized for graph work; unit tests | 5 | P1 | E7-01 |
| E14-04 | "What the AI saw" view | Shows the exact masked payload sent to the LLM for a given call | 2 | P2 | E14-03 |
| E14-05 | Encryption at rest (demo scope) | Uploaded files encrypted with a key from env (Fernet/AES); decrypted on read | 3 | P2 | E2-01 |
| E14-06 | Protected attributes exclusion | Engine and scoring have no inputs for gender, religion, ethnicity, personal hometown; test asserts schema | 1 | P2 | E12-02 |
| E14-07 | Fairness report | Compare pass rate and haircut distribution Micro vs Medium SME across synthetic cases | 3 | P2 | E15-01 |
| E14-08 | Data retention & deletion | Delete-case endpoint removes files and derived data; deletion itself audit-logged | 2 | P2 | E9-05 |
| E14-09 | Architecture & compliance page | In-app page describing FSI cloud target (Azure Thailand region, ISO 27001/SOC 2, TLS 1.3, AES-256, no training on customer data) and what is implemented vs planned | 2 | P1 | — |

### E15 — Evaluation & PoC metrics
| ID | Item | Acceptance criteria | Pts | Pri | Deps |
|---|---|---|---|---|---|
| E15-01 | Synthetic case bank | Generator produces 50+ varied cases with ground-truth labels (loops, tiers, tags) | 5 | P1 | E1-02 |
| E15-02 | Extraction accuracy eval | Field-level accuracy + CER on labelled real/synthetic statements; report printed | 3 | P1 | E2-02, E15-01 |
| E15-03 | Loop detection eval | Precision / recall / false-positive rate vs ground truth; target FPR < 3% | 3 | P1 | E4-02, E15-01 |
| E15-04 | Performance benchmark | Time per case for 1,500 and 10,000 transactions; shown in UI ("analysed in N s") | 2 | P1 | E4-02 |
| E15-05 | Metrics dashboard | In-app page showing E15-02..04 results with the date they were measured | 3 | P2 | E15-02 |
| E15-06 | Time-saved estimator | Uses ITMX assumptions (15–20 h manual) vs measured system time to show TAT reduction; assumptions visible | 2 | P2 | E15-04 |

### E16 — Demo readiness & release
| ID | Item | Acceptance criteria | Pts | Pri | Deps |
|---|---|---|---|---|---|
| E16-01 | One-click demo reset | Script resets DB and seeds the Kitti case (and optional others) in < 10 s | 2 | P0 | E1-02 |
| E16-02 | Offline mode | With network off, the full demo path works using cached OCR/LLM responses | 3 | P0 | E7-01, E0-06 |
| E16-03 | Demo path smoke test | Playwright script clicks through the 5 demo moments; must pass before every commit in I7 | 5 | P1 | I3 done |
| E16-04 | Backup recording | Screen recording of the full demo path (with voice-over by T-07) | 1 | P0 | I4 done |
| E16-05 | Deployment | Hosted instance (e.g. Azure App Service / Render / Fly) + local fallback on laptop | 3 | P1 | E0-01 |
| E16-06 | Error & empty states | Friendly states for failed upload, unknown bank, low confidence, missing consent | 2 | P1 | E8-* |
| E16-07 | Visual polish pass | Spacing, typography, Thai font rendering, loading skeletons, subtle transitions | 3 | P1 | I3 done |
| E16-08 | Seed users & personas | CA "คุณสมชาย", RM "คุณมานี", SME owner "คุณกิตติ" with avatars | 1 | P1 | E14-01 |

---

## 5. Non-engineering backlog (teammates)

| ID | Item | Acceptance criteria | Owner | Pri | Needed by |
|---|---|---|---|---|---|
| T-01 | Collect real statements | 2–3 PDFs from the chosen bank(s), downloaded by account owners; passwords noted separately | Team | P0 | I1 |
| T-02 | Create a real cross-bank loop | Transfer e.g. 5,000 → 4,990 → 4,980 across 3 own accounts at different banks within 48h; download statements afterwards | Team | P1 | I2 |
| T-03 | Validate §3 numbers in a spreadsheet | Independent spreadsheet reproduces waterfall, DSCR 1.05/1.35, safe limit 3.5M; any mismatch reported | Finance person | P0 | I2 |
| T-04 | Sample e-Tax invoices / ภ.พ.30 | Collect public ภ.พ.30 form + ETDA e-Tax invoice spec/examples; confirm field names | Team | P0 | I1 |
| T-05 | Fix ITMX.md inconsistencies in the deck | Waterfall math, DSCR on cash flow (not revenue), 450k date, "DAG" wording → "temporal loop detection" | Pitch lead | P0 | I3 |
| T-06 | Pitch deck | Problem → 4 pillars → live demo → architecture (Live vs Sandbox) → business model → moat → ask | Pitch lead | P0 | I6 |
| T-07 | Demo script & rehearsal | 3-minute script for the 5 demo moments; 5 timed rehearsals; voice-over for E16-04 | Presenter | P0 | I7 |
| T-08 | Judge Q&A bank | Answers for: hallucination, BOT/regulation, PDPA, why banks won't build it, PromptBiz access, accuracy numbers | Team | P1 | I6 |
| T-09 | Exploratory testing | Test each increment build; file bugs with steps + screenshot | Team | P1 | I2 onward |
| T-10 | Persona & UX copy (Thai) | Thai UI strings, button labels, memo wording reviewed for banking tone | Team | P1 | I3 |

---

## 6. Demo moments (acceptance test for the whole sprint)

1. **Upload → pipeline progress** — real PDFs go in, stages tick through, "analysed in N s".
2. **Loop graph lights up** — 3.8M of fake turnover found and netted, with the 3-hop loop animated.
3. **Click a number → orange box on the real PDF** — SHA-256 verified.
4. **Accept 450,000 with a reason** — numbers ripple, safe limit moves, audit entry appears; "Verify audit trail" passes.
5. **Slider 5.0M 🔴 → 3.5M 🟢 → export the 1-page memo** — with the Trade Line suggestion and CA sign-off.

If all five run offline on a freshly reset laptop, the sprint goal is met.
