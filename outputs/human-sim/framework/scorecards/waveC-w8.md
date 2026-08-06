# Wave C — W8 (save / export / share / PDF) — Scorecard

- **Persona:** P5 — Skeptical CFO / exec
- **Workflow:** W8 — save to records, export cost PDF/CSV/JSON, share link (public read-only)
- **Date:** 2026-07-10
- **Stack:** worktree `waveC-w8` @ e3e9308 · backend `:8051` (db `cadverify_w8`) · frontend `:3051`
- **Surfaces driven (real clicks, Playwright + vision):**
  - `/verify` → Records screen (`records-screen.tsx`) — the system-of-record
  - Cost a real part (`backend/tests/assets/cube.step`, STEP) → auto-persisted `CostDecision`
  - Record detail: **Export PDF**, **CSV (drivers)**, **JSON**, **Create share link**
  - Public share page (signed-out): `/s/cost/{short_id}` (`app/s/cost/[shortId]/page.tsx`)
  - Backend: `api/cost_decisions.py` (pdf / export.json / export.csv / share / public view),
    `services/cost_pdf_service.py` (WeasyPrint), `services/cost_decision_service.py` (sanitize/CSV/share)

## Verdict on the CFO's core question — does the exported/shared artifact keep provenance + honesty?
**YES — honesty travels with every artifact.** The PDF, CSV, JSON, and the public signed-out
share page all carry: `confidence_validated = False`, the explicit label
*"assumption-based, not yet validated"*, the ±40% error band, per-driver provenance tags
(`DEFAULT`/`MODEL`), and an explicit *"not a validated quote"* disclaimer. Nothing is promoted
to "fact" on export. The one defect found is cosmetic (a mangled `×` glyph in the PDF), not an
honesty regression.

---

## Category vector (Bucket A — PRODUCT; 0–100, min = overall)

| # | Category | Score | Note |
|---|----------|------:|------|
| 1 | Functional correctness | 95 | Cost→persist→records→open→PDF/CSV/JSON→share all fire correctly; artifacts download with correct names |
| 2 | Data fidelity | 97 | Exported numbers match on-screen & each other; provenance + honest CI preserved verbatim across PDF/CSV/JSON/share |
| 3 | AI fidelity | 96 | should-cost/routing disclose `validated=false` + basis "no ground truth yet"; no number presented as measured |
| 4 | Interaction fidelity | 94 | buttons, busy states ("Exporting…"), keyboard nav (h/r), downloads all behave |
| 5 | **Visual fidelity** | **80** | **PDF bounding-box renders literal `&times;` instead of `×` (double-escape). Web/share render correctly.** ← overall gate |
| 6 | Performance | 85 | cost ~14 s (STEP mesh); first PDF gen ~10 s (WeasyPrint, then file-cached); CSV/JSON instant; 48-estimate PDF = 50 pages |
| 7 | Reliability | 92 (partial) | flow repeated consistently across runs; PDF file-cached; no formal N-run |
| 8 | Conversational | n/a | no chat surface in W8 |
| 9 | Error recovery | 93 | export-before-cost = honest empty state, zero dangling export buttons; revoke → link 404s |
| 10 | **Security** | **97** | cross-org 404 on detail/pdf/export.json/export.csv/POST-share; public share PII-free (allow-list); unauth list 401; `noindex`+`no-store` on share |
| 11 | Accessibility | 70 (partial, low-conf) | real `<button>` elements; not deeply audited (focus order / contrast / SR) |
| 12 | Regression | n/a | registry replay out of scope for this run |

**Overall (min across exercised) = 80** — gated by the PDF `&times;` visual defect.

---

## Findings

### F1 — PDF cost report renders literal `&times;` instead of `×` in the bounding box  (MAJOR-cosmetic / the #1 fix)
```
persona: P5 CFO   flow: export cost PDF   branch: happy path   category: Visual fidelity (5)
observed:  Geometry table "Bounding box (mm)" cell shows  "20.0 &times; 15.0 &times; 10.0"
           (the HTML entity printed literally) — see w8-07-pdf-page.png
expected:  "20.0 × 15.0 × 10.0"  (as the web record-detail and the public share page both render)
evidence:  w8-07-pdf-page.png (rendered PDF page 1); dl/cube-cost-report.pdf
failure_reason: templates/pdf/cost_report.html line 62:
           {{ geo.get('bbox_mm', []) | join(' &times; ') }}
           The join argument is a Jinja EXPRESSION output, and the env has
           autoescape=select_autoescape(("html","xml")) → `&times;` is escaped to
           `&amp;times;`, which WeasyPrint prints as the literal text "&times;".
           (The header cells `cm&sup3;`/`cm&sup2;` are literal template HTML, NOT inside
           a {{ }}, so they render fine — proving it's the autoescape-of-expression path.)
severity: minor/polish  (cosmetic; the number is correct, only the separator glyph is wrong)
confidence: certain (root-caused in template + confirmed visually in the PDF)
recommended_fix: join with a real multiplication sign, not an entity, e.g.
           {{ geo.get('bbox_mm', []) | map('round', 1) | join(' × ') }}
           (a literal "×" / U+00D7 survives autoescape untouched). Or mark the
           joined string |safe after building it from already-safe numeric parts.
status: open
```

### F2 — First-time PDF generation ~10 s; report is 50 pages for one part  (MINOR / perf+visual)
```
persona: P5 CFO   flow: export cost PDF   category: Performance (6) / Visual (5)
observed:  "Export PDF" → download completed in ~10.2 s on first request (WeasyPrint render of
           48 per-process estimates × 6 quantities → 50-page PDF). Subsequent requests served
           from file cache (fast).
expected:  A CFO expects a snappy export and a report they can skim; 50 pages for one cube is heavy.
evidence:  pdfMs=10184 in the run log; w8-07-pdf-page.png shows 1/50 pages.
severity: minor   confidence: high
recommended_fix: consider a "recommended + make-vs-buy summary" default with a full-detail
           appendix behind a flag; and/or warm the cache on decision-persist. Honesty unaffected.
status: open
```

### F3 (POSITIVE) — Cross-org isolation on every export/share route is airtight
```
category: Security (10)
observed:  Org B (fresh signup, empty records) requested Org A's decision ULID
           01KX647EDM8021VDR5SZH7EVKF on: (detail) /pdf /export.json /export.csv POST /share
           → ALL returned 404 (invisibility, not 403 existence-leak). Org B own list = 200 empty.
evidence:  w8cross run: crossOrg = [detail 404, /pdf 404, /export.json 404, /export.csv 404, POST /share 404]
confidence: certain   status: pass
```

### F4 (POSITIVE) — Public share leaks no PII and is correctly scoped
```
category: Security (10) / Data fidelity (2)
observed:  Signed-out GET /s/cost/{short} → 200 with allow-listed keys only
           (filename,file_type,label,created_at,make_now_process,crossover_qty,quantities,
            geometry,material_class,routing,estimates,decision,assumptions,engine_feasibility,
            notes,status). No user_id / api_key / mesh_hash / params_hash / email in payload.
           Response headers: X-Robots-Tag: noindex, Cache-Control: private,no-store; page robots noindex.
           Revoking the share makes the link 404 immediately (code + copy verified).
evidence:  w8-08-share-signedout.png; apiSharePiiHit=false; apiShareKeys (above)
confidence: certain   status: pass
```

### F5 (POSITIVE) — Honesty preserved verbatim across ALL exported artifacts
```
category: Data fidelity (2) / AI fidelity (3)
observed:
  - CSV: every row carries confidence_label="assumption-based, not yet validated",
    confidence_validated=False, est_error_band_pct, confidence_low/high. (dl/cube-cost.csv)
  - JSON: estimates[].confidence.validated=False, basis "…no ground truth yet",
    assumptions[].provenance="DEFAULT". (dl/cube-cost.json)
  - PDF: prominent banner "Assumption-based should-cost … not yet validated … Use as a
    negotiation and design baseline, not a quote"; per-driver provenance column. (w8-07-pdf-page.png)
  - Public share: "not a validated quote" banner + 80% confidence band + DEFAULT-tagged
    assumptions. (w8-08-share-signedout.png)
  Numbers cross-check: record-detail Σ line items $8.68 / band $5.21–$12.15  == CSV fdm/qty1000;
  share make-now $18–$42 == CSV fdm/qty1. Exported == on-screen.
confidence: certain   status: pass
```

### F6 (POSITIVE) — Export-before-cost branch is graceful
```
category: Error recovery (9)
observed:  Records screen with zero decisions shows "No records yet — and that's the point."
           + a "Verify your first part" CTA and NO export/share buttons at all (those live only
           inside a record detail). No broken/disabled dangling affordances.
evidence:  w8-02-records-empty.png
status: pass
```

---

## Screenshots (in `waveC-shots/`, all prefixed `w8-`)
- `w8-01-verify-home.png` — post-login /verify home
- `w8-02-records-empty.png` — empty records (export-before-cost branch)
- `w8-03-costed-part.png` — verification pipeline overlay mid-cost (cube.step)
- `w8-04-records-populated.png` — record persisted after cost
- `w8-05-record-detail.png` — glass-box record with provenance chips + honest CI, export/share buttons
- `w8-06-shared.png` — share link created (authenticated view)
- `w8-07-pdf-page.png` — rendered cost PDF page 1 (shows honesty banner + the `&times;` bug)
- `w8-08-share-signedout.png` — public share opened SIGNED-OUT (honesty + no PII)
- `w8-09-orgB-empty-records.png` — org B (attacker) empty workspace during cross-org probe
- `w8-cube-cost-report.pdf` — the actual exported PDF artifact

## Artifacts inspected
- `dl/cube-cost-report.pdf` · `dl/cube-cost.csv` · `dl/cube-cost.json` (scratchpad)
