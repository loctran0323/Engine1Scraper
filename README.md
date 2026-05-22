# Engine1Scraper — VAIntage Pathways™ "Brain"

Automated ingestion pipeline that scrapes federal & Florida-specific MAT billing
rules and clinical guidelines, transforms them into the **Engine 1 JSON Rule
Matrix** (financial guard) and **Engine 2 RAG corpus** (clinical guard) used by
the VAIntage Desktop Agent.

> Phase 2–5 of the *VAIntage Pathways Accelerated Summer Internship Project Timeline*

---

## Architecture

```
   ┌─────────────────────────────────────────────────────────┐
   │  SOURCES (public + subscription-gated)                  │
   │   • CMS IOM Pub 100-02 Ch 17 (OTP benefit policy)       │
   │   • CMS IOM Pub 100-04 Ch 39 (OTP claims processing)    │
   │   • CMS MLN OTP Booklet (MLN8296732)                    │
   │   • CMS NCCI PTP Edits (quarterly ZIP)                  │
   │   • FL AHCA Community Behavioral Health Services        │
   │   • FCSO (FL Medicare MAC) OTP Specialty Page           │
   │   • eCFR Title 42 Part 8 (federal OTP regulation)       │
   │   • SAMHSA TIP 63 (MAT clinical guidelines)             │
   └─────────────────────────────────────────────────────────┘
                              │
                              ▼  scrapers/  (BeautifulSoup, lxml, pdfplumber, Selenium)
   ┌─────────────────────────────────────────────────────────┐
   │  RAW PAYLOADS → data/raw/<source_key>/<sha12>.{pdf,xml,html}
   │  PARSED       → data/processed/<source_key>.json        │
   └─────────────────────────────────────────────────────────┘
                              │
              ┌───────────────┴────────────────┐
              ▼                                ▼
   transformers/json_matrix.py       transformers/vector_chunker.py
   ┌─────────────────────────┐       ┌──────────────────────────┐
   │ Engine 1 Rule Matrix    │       │ Engine 2 RAG chunks      │
   │ (federal → FL overrides)│       │ (windowed, stable IDs)   │
   └─────────────────────────┘       └──────────────────────────┘
              │                                │
              ▼                                ▼
        qa/diff_checker.py            data/vector/engine2_chunks.json
   ┌─────────────────────────┐               (→ vector DB)
   │ Diff vs live matrix     │
   │ (alert-fatigue gate)    │
   └─────────────────────────┘
              │
              ▼
   data/processed/engine1_matrix.{candidate,live}.json  (→ Desktop Agent)
```

## Quick start

```bash
# 1. Install
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 2. Run all scrapers
python main.py

# 3. Run only one source
python main.py --only ecfr_42_part_8

# 4. See a human summary
python inspect_run.py

# 5. Drill into one source's parsed payload
python inspect_run.py cms_pub_100_04_ch39

# 6. Generate manager-friendly CSV + Markdown reports
python report.py
```

After a run, the **`reports/`** directory will contain:

| File | Purpose |
|---|---|
| `run_summary.md` | One-page digest — email or paste into Slack |
| `run_summary.csv` | Per-source status, byte counts, SHA hashes |
| `engine1_rules.csv` | Flat table of every generated billing rule |
| `engine2_chunks.csv` | All RAG chunks with previews |

## Promoting a candidate matrix to "live"

The pipeline writes every run as a `*.candidate.json` and never auto-overwrites
the live matrix. To promote (after reviewing the diff report):

```bash
python main.py --promote
```

This copies `engine1_matrix.candidate.json` → `engine1_matrix.live.json` **only
if** the diff report flagged a material change. Prevents silent rule drift.

## Project layout

```
Engine1Scraper/
├── config.py                  # All source URLs + cadences (single source of truth)
├── main.py                    # End-to-end orchestrator
├── inspect_run.py             # Human-readable run summary
├── report.py                  # CSV + Markdown report generator
├── scrapers/
│   ├── base.py                # Retries, caching, content hashing
│   ├── cms_scraper.py         # Pub 100-02, Pub 100-04, MLN booklet
│   ├── samhsa_scraper.py      # eCFR 42 CFR Part 8 + TIP 63
│   ├── ahca_scraper.py        # FL AHCA handbook (with Selenium fallback)
│   ├── ncci_scraper.py        # NCCI quarterly PTP edits
│   └── fl_mac_scraper.py      # FCSO OTP specialty page
├── transformers/
│   ├── json_matrix.py         # Scrape → Engine 1 rule matrix
│   └── vector_chunker.py      # Scrape → Engine 2 RAG chunks
├── qa/
│   └── diff_checker.py        # Candidate vs live matrix diff
├── azure_functions/
│   └── timer_trigger/         # Phase 5 — Azure Functions cron wrapper
├── data/                      # (gitignored) raw + processed payloads
└── reports/                   # CSV + MD outputs for stakeholders
```

## Engine 1 rules currently generated

| Rule ID | Payer | Code | Modifier | Logic | Source |
|---|---|---|---|---|---|
| `R-FED-01` | Medicare Advantage | G2067 | — | BundleValidation | CMS Pub 100-04 Ch 39 |
| `R-FL-02` | Managed Medicaid | H0020 | POS-58 | PointOfCareBlock | FL AHCA |
| `R-FL-03` | AHCA Medicaid | All SUD | HF | SubstanceAbuseModifier | FL AHCA |
| `R-FL-04` | AHCA Medicaid | H0020 | HD→HG | ModifierSequencer | FL AHCA |
| `R-FLMAC-01` | Medicare | G2067 | — | PayerBlocker | FCSO |
| `R-SIMPLY-01` | Simply MCO | COUNSELING | — | CounselingTimeMinimum | Simply Provider Manual |

Federal rules execute **before** Florida-specific overrides, per the addendum.

## Source matrix

| Source key | Type | Cadence | Engine | Status |
|---|---|---|---|---|
| `cms_pub_100_04_ch39` | PDF | monthly | 1 | ✅ live |
| `cms_pub_100_02_ch17` | PDF | monthly | 1 | ✅ live |
| `cms_mln_otp_booklet` | PDF | bi-annually | 1 | ✅ live |
| `cms_ncci_edits` | ZIP | quarterly | 1 | ✅ live (0 OTP edits this Q) |
| `fl_ahca_cbh_handbook` | HTML | quarterly | 1 | ✅ live |
| `fl_mac_fcso_otp` | HTML | bi-annually | 1 | ✅ live |
| `ecfr_42_part_8` | JSON/XML API | ad-hoc | 2 | ✅ live |
| `samhsa_tip_63` | PDF | bi-annually | 2 | ✅ live |
| `sunshine_provider_manual` | PDF | monthly | 1 | ✅ live |
| `simply_provider_resources` | PDF | quarterly | 1 | ✅ live |
| `cdc_icd10_z_codes` | PDF | annually | 2 | ✅ live |
| `asam_criteria` | gated | ad-hoc | 2 | 🔒 subscription required |

## Azure Functions deployment (Phase 5)

The `azure_functions/timer_trigger/` directory contains a serverless wrapper
that invokes `main.run()` on a cron schedule. To deploy:

```bash
# Prereqs: Azure CLI + an Azure Function App in your subscription
az login
func azure functionapp publish <your-function-app-name> --python
```

Configure two environment variables on the Function App:
- `BRAIN_SOURCES` (optional, comma-separated source keys to run; default = all)
- `BRAIN_PROMOTE` (`true` to auto-promote candidate → live when diff is material)

For separate federal-vs-Florida cadences, deploy two Functions with different
`BRAIN_SOURCES` values and different `schedule` strings in their respective
`function.json` files.

## Known limitations / iterations

- **NCCI delta-only**: the CMS landing page links to the quarterly
  *additions/deletions* zip, not the full PTP table. If CMS makes no OTP edit
  changes in a given quarter, we get 0 rows for OTP — that's accurate, not a
  bug. To get the full PTP universe, switch to the full quarterly tables
  (4 xlsx files, ~2.5M rows total) — needs a streaming xlsx parser.
- **AHCA modifier extraction**: the MAT-specific AHCA PDFs (Methadone Criteria,
  PT 2021-25) cover clinical criteria and drug coverage but don't enumerate
  modifier rules. The R-FL-* rules are hardcoded from the addendum spec; the
  scraped PDFs serve as diff-tracked source-of-record so changes get flagged.
- **Sunshine / Simply manuals** describe processes, not code-to-diagnosis maps.
  R-SUNSHINE-01 will only fire if the manual starts listing specific H-codes
  alongside required F11.x diagnoses.
- **ASAM Criteria** is subscription-gated; needs institutional credentials.
- **Engine 1 latency budget** is 200ms — current matrix is well under that, but
  if the rule count grows, evaluate whether the agent needs an index.

## Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| `403 Forbidden` from SAMHSA | UA tripped Cloudflare. Confirm `USER_AGENT` in `config.py` is plain Chrome (no bot prefix). |
| `404 Not Found` for a PDF | CMS/AHCA reorganized. Update the `url=` in `config.py` and validate with `curl -I "$URL"`. |
| `No module named 'selenium'` | `pip install selenium webdriver-manager`. Needed only for AHCA's JS fallback. |
| `zsh: unknown file attribute: ~` when pasting commands | Run `setopt INTERACTIVE_COMMENTS` (or just paste commands without `# comments`). |

## License & data sources

All scraped content is from public-domain U.S. federal & state government
publications, plus SAMHSA materials (public). ASAM Criteria is excluded
pending institutional licensing.
