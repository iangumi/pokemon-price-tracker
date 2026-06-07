# Architecture Overview

## What This Tool Does

A daily/on-demand **Pokemon card price checker** for Tokopedia store listings. It scrapes competitor prices from Tokopedia, eBay, and SnkrDunk, compares them against your own listings, flags pricing gaps, and generates HTML/MD/CSV reports.

---

## Technology Stack

| Layer | Technology |
|---|---|
| **Web Framework** | Flask 3.x |
| **Frontend** | Single HTML SPA — Alpine.js + AG Grid Community (all in `static/index.html`) |
| **Templates** | Jinja2 (used for static report generation only) |
| **Persistence** | SQLite (`data/price_history.sqlite3`) |
| **HTTP Client** | stdlib `urllib` with gzip decompression/retry logic, plus optional Scrapling backend |
| **AI Summaries** | MiniMax API (OpenAI-compatible endpoint) |
| **CLI** | `argparse` with subcommands: `run`, `sync-store`, `seed-config`, `validate-config`, `inspect-run`, `migrate-snkrdunk-urls` |
| **Testing** | `unittest` tests, pytest-compatible |

---

## Directory Structure

```
pokemon_price_scheduler/
├── __main__.py                  # Entry point: python -m pokemon_price_scheduler
│
├── domain/                      # PURE business logic — no I/O, fully testable
│   ├── models.py               # Frozen dataclasses: Product, Source, PriceObservation,
│   │                            #   SourceResult, ProductAnalysis, utc_now(), alert_label()
│   ├── analysis.py              # analyze_product(), score_observations(), relevance_score()
│   ├── card_parser.py           # parse_card_identity(), CardIdentity (frozen)
│   └── text.py                  # clean_text() utility
│
├── infrastructure/              # All external I/O — NO cross-infrastructure imports
│   ├── http.py                 # fetch_text() — gzip, retries, two header sets (default + Cloudflare bypass)
│   ├── parsing.py              # parse_price_to_idr(), extract_json_objects(), walk_json(),
│   │                            #   reject_low_tokopedia_outliers()
│   ├── scrapers.py             # MarketplaceScraper + extract_tokopedia_search_items(),
│   │                            #   extract_ebay_items(), extract_snkrdunk_api()
│   ├── history.py              # SQLite persistence (thread-local connections via threading.local)
│   ├── reports.py              # ReportEngine + 6 concrete Report subclasses
│   └── ai.py                  # MiniMaxClient, attach_ai_summaries()
│
├── v2/                           # Newer pipeline trace storage and run persistence
│   └── storage.py              # TraceStore, schema migration, run result persistence
│
├── templates/                    # Jinja2 templates (static report generation only)
│   ├── base.html               # Shared shell with sidebar, topbar, CSS design tokens
│   ├── dashboard.html
│   ├── card_detail.html
│   ├── opportunities.html
│   └── renderers.py           # render_dashboard(), render_card_detail(), render_opportunities()
│
├── static/
│   ├── index.html             # **Served by Flask** — live SPA shell
│   └── vendor/ag-grid/        # Vendored AG Grid Community runtime and theme assets
│
├── cli.py                       # CLI: run, sync-store, seed-config
├── inventory.py                 # SQLite cards/listings/sales/opportunities/inventory model
├── ui_components.py             # Shared live-app HTML/AG Grid component builders
├── web.py                       # Flask app (serves SPA + API endpoints)
├── config.py                    # JSON config load/save for products.json
└── store_sync.py               # get_active_store_product_urls() — detects sold products
```

---

## Core Design Patterns

### Layered Architecture (Domain / Infrastructure Split)

- **`domain/`** — Pure functions and frozen dataclasses. Zero imports to any infrastructure code. Fully unit-testable without network or servers.
- **`infrastructure/`** — All external I/O. No cross-infrastructure imports (e.g., `scrapers.py` imports `http.py` and `parsing.py` but NOT `history.py` or `ai.py`).
- **Root modules** — Backward-compat shims re-exporting from layered packages. Existing import paths in `cli.py`, `web.py`, and tests continue to work unchanged.

### Thread-Local SQLite Connections

`infrastructure/history.py` uses `threading.local()` so each thread gets its own `sqlite3.Connection`. This is safe for the Flask dev server's threaded mode and the background scheduler thread.

### Run Trace and Price History

SQLite stores both run trace data and daily workflow data:

- `runs` - scheduler executions
- `product_results` - latest per-product analysis rows for each run
- `observations` - scraped source listings
- `source_fetches` - raw fetch status and source-level diagnostics
- `analysis_decisions` - filtering and scoring decisions
- `price_history` - one price snapshot per card after each scheduler run
- `cards` - stable parsed card identity records for inventory/sales
- `listings` - Tokopedia listing lifecycles linked to cards
- `sales` - completed sale records with sold date, sold price, bought price, and net income
- `opportunities` - persistent buy-list candidates with source/link/price and conversion audit fields
- `inventory_items` - owned stock records created from opportunities and linked to optional listings

`price_history` records `card_id`, `tokopedia_price`, `market_avg_price`, `delta_percent`, `alert_status`, `source_summary`, and `created_at`. It also stores run/result references where available. Snapshots are inserted from both the legacy `save_run()` path and the v2 `TraceStore.save_results()` path, so scheduler runs update history regardless of which persistence path is used.

`inventory.py` owns the `cards` / `listings` / `sales` / `opportunities` / `inventory_items` schema. During this transition, `config/products.json` remains scheduler-compatible source config, while SQLite is the source of truth for sale analytics, opportunity audit history, and owned inventory. Web mutations mirror lifecycle changes into both places when a listing must be scheduler-visible.

### Inventory and Sales Lifecycle

- A `card` is the parsed identity: name, set, number, rarity, language, and condition.
- A `listing` is one Tokopedia listing lifecycle. Active cards and sold cards are listing states, not separate product types.
- A `sale` is created when a listing is manually marked sold or when existing sold-card details are edited.
- Restocking a sold card creates a new active listing lifecycle and preserves the prior sold listing and sale row.
- Sale fields currently captured: `sold_at`, `sold_price_idr`, `bought_at_price_idr`, and `net_income_idr`.
- Net income is manual. Sold price and bought price are stored separately to support future marketplace fee, profit, margin, and ROI calculations.

### Opportunities and Owned Inventory

- The live `/opportunities` page is a persistent buy list, separate from the generated `reports/opportunities.html` discovery report.
- An opportunity captures card name, rarity, language, source, source link, and observed buy price.
- `/opportunities/<slug>` shows a detail-page layout with a conversion action.
- Conversion always creates an `inventory_items` row with the confirmed bought price.
- If conversion includes both Tokopedia listing URL and listing price, the app also appends an active product to `config/products.json` and creates a SQLite `listing` lifecycle for Store Listings/Repricing Queue.
- If listing URL and listing price are omitted, conversion records owned inventory only. The item appears on `/inventory` but not in Store Listings, scheduler runs, or Repricing Queue.
- Converted opportunities are marked `converted` and keep `converted_at`, `converted_card_id`, `converted_listing_id`, and `converted_inventory_item_id` for auditability.

### Background Scheduler via Subprocess + SSE

`web.py` runs the full `python -m pokemon_price_scheduler run` as a **subprocess** (not a thread) for the background scheduler. Progress is streamed back to the frontend via **Server-Sent Events (SSE)** at `/run/status`. Individual card refreshes also run as background threads that poll a shared `dict` for status.

### Report Engine (Strategy Pattern)

`infrastructure/reports.py` defines an abstract `Report` base class. `ReportEngine` orchestrates all 6 concrete reports, but each can be instantiated and run independently:

| Class | Output |
|---|---|
| `MarkdownReport` | `reports/latest.md` |
| `CSVReport` | `reports/latest.csv` |
| `SVGSummaryReport` | `reports/charts/*.svg` |
| `CardDetailReport` | `reports/cards/*.html` |
| `DashboardReport` | `reports/dashboard.html` |
| `OpportunitiesReport` | `reports/opportunities.html` |

### SPA + API Backend

`web.py` serves two roles simultaneously:
1. **Static file server** — `static/index.html` for all SPA routes (`/`, `/cards`, `/cards/<slug>`, `/inventory`, `/reports`, `/opportunities`, `/opportunities/<slug>`, `/repricing`, `/soldcards`)
2. **API backend** — HTML fragments and JSON at `/api/*` endpoints fetched by the SPA via `fetch()`

The live app uses a retro handheld design system in `static/index.html`: LCD-green panels, square controls, inline SVG menu/KPI icons, dense AG Grid tables, and compact dashboard previews. Server-rendered fragments are built in `ui_components.py`.

---

## Core Data Models (from `domain/models.py`)

All models are `@dataclass(frozen=True)`.

### `Product`
Central entity. Fields: `title`, `own_price_idr`, `tokopedia_url`, `search_terms`, `sources`, `status` (`active`/`sold`), `sold_at`, `added_at`.
- **`card_identity`** (lazy property): parsed via `parse_card_identity()` from `domain/card_parser.py`
- **`slug`** (lazy property): URL-safe identifier derived from card identity

### `CardIdentity` (from `domain/card_parser.py`)
Parsed from a product title. Fields: `name`, `set_symbol`, `card_number`, `rarity`, `condition`, `language`.
- Query methods: `tokopedia_query()`, `ebay_query()`, `snkrdunk_query()` — return compact search strings

### `PriceObservation`
A single scraped data point. Fields: `source_name`, `source_kind`, `url`, `price_idr`, `title`, `currency`, `raw_price`, `is_legit`, `relevance_score`

### `ProductAnalysis`
Main output of a run. Fields: `product`, `run_at`, `source_results[]`, `market_min/median/average`, `price_delta_percent`, `alert_level` (`red`/`amber`/`none`), `underpriced_by_idr`, `underpriced_by_percent`, `recommendation`, `ai_summary`

### Alert Levels
- `red` — price delta >= 12% above market
- `amber` — price delta >= 10% above market
- `none` — within acceptable range

---

## Key Algorithms

### Price Relevance Scoring (`domain/analysis.py`)
`relevance_score(title, name, set_symbol, rarity, condition)` — scores 0–100 how well a marketplace listing matches the target card. Considers:
- Exact name match (or significant word overlap)
- Set symbol match
- Rarity match (exact or broader category)
- Condition match (exact PSA/BGS grade or condition keyword)

### Price Analysis Pipeline (`analyze_product()`)
1. Score all observations by relevance
2. Filter observations by `comparable_min/max_ratio_to_own` (config tunable)
3. Filter Tokopedia outliers using `reject_low_tokopedia_outliers()` (median floor rule)
4. Compute market min, median, average
5. Compute `price_delta_percent = (own_price - global_average) / global_average * 100`
6. Set alert level
7. Generate recommendation text

### Card Identity Parsing (`domain/card_parser.py`)
`parse_card_identity(title)` extracts:
- **name**: everything before first ` - ` delimiter, stripped of rarity/set/PSA suffixes
- **set_symbol**: regex `sv\d+|s\d+|m\d+|...`
- **card_number**: regex `\d{1,3}/\d{1,3}` (e.g. `114/080`)
- **rarity**: `SAR, SR, UR, AR, IR, SIR, SEC, RR, R, CHR, CSR, PROMO`
- **condition**: `PSA 9`, `BGS 9.5`, `raw NM`, etc.
- **language**: `Japanese`, `English`, `Indonesian`, `Unknown` (keyword detection)

---

## Web API Routes (from `web.py`)

| Route | Method | Purpose |
|---|---|---|
| `/` | GET | Serves `static/index.html` |
| `/cards`, `/cards/<slug>`, `/inventory`, `/reports`, `/repricing`, `/opportunities`, `/opportunities/<slug>`, `/soldcards` | GET | SPA routing — all serve `static/index.html` |
| `/api/dashboard` | GET | Dashboard Live Store Signals, Active Cards preview, and Repricing Queue preview |
| `/api/cards` | GET | Cards grid HTML fragment |
| `/api/cards/<slug>` | GET | Card detail HTML fragment |
| `/api/inventory` | GET | Owned inventory grid from active/sold listing lifecycles and converted opportunities |
| `/api/reports` | GET | Reports page HTML fragment with report links and Source Health |
| `/api/repricing` | GET | Repricing Queue HTML fragment |
| `/api/cards/<slug>/mark-sold` | POST | Mark active listing sold and record sold price, bought price, sold date, and net income |
| `/api/cards/<slug>/sale-details` | POST | Edit sale details for existing sold cards |
| `/api/cards/<slug>/revert-sold` | PUT | Restock a sold card by creating a new active listing lifecycle |
| `/api/cards/<slug>/update-price` | PUT | Fetch current Tokopedia listing price |
| `/api/opportunities` | GET | Persistent buy-list opportunities table HTML fragment |
| `/api/opportunities` | POST | Create a new buy-list opportunity |
| `/api/opportunities/<slug>` | GET | Opportunity detail fragment |
| `/api/opportunities/<slug>/convert` | POST | Convert opportunity into owned inventory, and optionally an active Store Listing |
| `/api/soldcards` | GET | Sold cards grid HTML fragment |
| `/api/products/sync` | POST | Sync new products from Tokopedia store page |
| `/api/cards/add` | POST | Add new card by URL |
| `/api/cards/<slug>/search-term` | PUT | Update search keyword |
| `/run` | POST | Trigger full scheduler run (subprocess) |
| `/run/status` | GET | SSE stream: scheduler progress events |
| `/run/<slug>` | POST | Background refresh for single card |
| `/run/<slug>/status` | GET | Poll single-card refresh status |
| `/latest.md` | GET | Raw markdown report |
| `/latest.csv` | GET | Raw CSV report |
| `/charts/<slug>.svg` | GET | SVG price history chart |

---

## Repricing Queue

The daily repricing workflow is exposed at `/repricing` and backed by `history.repricing_queue()`. It classifies cards using the latest Tokopedia and market average prices:

- `Lower price` when delta is above +10%
- `Raise price` when delta is below -10%
- `Missing market data` when market average is unavailable
- `Aligned` when delta is within +/-10%

Suggested prices are calculated from market average:

- Quick Sale = `market_avg_price * 0.92`
- Normal = `market_avg_price * 0.98`
- Max Profit = `market_avg_price * 1.05`

The page includes summary counts, action filters, delta/price sorting, and AG Grid-native column sizing.

## Live Dashboard and Reports

The live dashboard is intentionally not a full report. It is a first-screen operating surface:

- `Live Store Signals` wraps Active Listings, Portfolio Value, Market Value, Active Alerts, and Latest Run.
- Portfolio and market values use compact dashboard formatting (`Rp x.xM`), while full grids keep full IDR formatting.
- `Active Cards` previews the highest-value active Tokopedia listings.
- `Repricing Queue` previews actionable rows first: Lower price, Raise price, Missing market data, then Aligned.
- Source Health diagnostics live on `/reports` and `/api/reports`, alongside `latest.md` and `latest.csv` links.

The dashboard, reports, card detail, and grid pages are all server-rendered HTML fragments fetched by the Alpine SPA. This keeps behavior Python-testable while avoiding a separate frontend build pipeline.

## SPA Architecture (`static/index.html`)

Single HTML file with:
- **`app()`** Alpine.js component: manages `currentPage`, `pageTitle`, `pageMeta`, `pageContent`, `schedulerState`, `toasts[]`
- **`navigateTo(path)`**: fetches `/api/*` HTML fragments, renders into `#content`, initializes AG Grid mounts
- **Inline SVG navigation icons**: embedded in the static shell; no icon dependency or network fetch
- **AG Grid adapter**: reads `data-columns` and `data-rows` from generated fragments, creates grids, and stores APIs in `window._agGridById`
- **Repricing controls**: `filterRepricing(action)` and `sortRepricing(mode)` call AG Grid filter/sort APIs for the daily queue
- **EventSource (`/run/status`)**: SSE client for live scheduler progress
- **Modals**: Add Card modal (URL + keyword inputs), Add Opportunity modal, Convert Opportunity modal
- **Sale modals**: Mark Sold/Edit Sale modal (sold date, sold price, bought price, net income)
- **Toast system**: `showToast(message, type)` with success/error/info variants
- **Opportunity operations**: `submitOpportunity()` creates buy-list rows; `submitConvertOpportunity()` converts them into inventory and optional Store Listings
- **Scheduler operations**: `refreshCard()`, `syncNewProducts()`, `addCard()`, `updateSearchTerm()`, `revertSold()`, `updatePrice()`, `submitMarkSold()`

---

## CLI Subcommands (`cli.py`)

### `run`
Full pipeline: detect sold products → filter by `min_price_idr` → scrape all sources → optionally add AI summaries → save to SQLite → write all reports.

Key flags: `--config`, `--limit`, `--ai-summary`, `--min-price-idr`, `--fetch-backend`, `--no-sold-detection`

### `sync-store`
Scrapes a Tokopedia store page to extract active product URLs. Writes `data/store_products.json`. Used to detect which products have been marked sold.

### `seed-config`
Reads `store_products.json`, runs `parse_card_identity()` on each title to generate search terms, creates `Source` entries for Tokopedia/eBay/Snkrdunk, writes `config/products.generated.json`.

---

## Configuration

### `config/products.json` / `config/products.generated.json`
```json
{
  "products": [
    {
      "title": "Meowth Ex SAR 114/080 m3 - Japanese",
      "own_price_idr": 150000,
      "tokopedia_url": "https://www.tokopedia.com/...",
      "search_terms": ["Meowth Ex SAR raw NM m3 Japanese"],
      "sources": [
        { "name": "tokopedia_find", "kind": "tokopedia_find", "url": "..." },
        { "name": "ebay_sold", "kind": "ebay_sold", "url": "..." }
      ],
      "comparable_min_ratio_to_own": 0.3,
      "comparable_max_ratio_to_own": 3.0
    }
  ],
  "settings": {
    "min_price_idr": 500000
  }
}
```

### Environment Variables
- `MINIMAX_API_KEY` — MiniMax API key for AI summaries
- `MINIMAX_MODEL` — defaults to `MiniMax-M2.7-highspeed`
- `MINIMAX_BASE_URL` — defaults to `https://api.minimax.io/v1`
- `MINIMAX_TIMEOUT_SECONDS` — defaults to `30`

---

## Design Rules for Future Changes

1. **Never import infrastructure into domain.** Keep `domain/` pure. If you need DB data in analysis, pass it in as arguments.
2. **No cross-infrastructure imports.** `scrapers.py` may not import `history.py` or `ai.py`.
3. **Frozen dataclasses** for all domain models — never mutate `Product` or `PriceObservation` in place.
4. **Price parsing is fragile** — Tokopedia HTML structure changes often. Keep extraction logic isolated in `infrastructure/scrapers.py` so it can be updated without touching analysis logic.
5. **The SPA is a single file** — `static/index.html` is the frontend. Don't split it into multiple static files; the Alpine.js component architecture handles modularity within that one file.
6. **Configurable thresholds** — alert levels and outlier rejection are tunable via `comparable_min/max_ratio_to_own` in the product config, not hardcoded.
7. **AG Grid classes are reserved** — avoid custom class names starting with `ag-`. AG Grid theme CSS targets broad `ag-*` selectors, so app wrappers should use names like `grid-shell`, `cards-data-grid`, and `ag-grid-host`.
