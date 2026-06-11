# Pokemon Store Price Scheduler

This tool checks your Tokopedia Pokemon card listings at or above Rp 500,000 against marketplace references, stores each run in SQLite, and helps you decide which cards need repricing.

It is designed to run both on demand and from a daily schedule.

## Agent Workflow

Coding agents should read `AGENTS.md` before making changes. It defines the project rule for large features and refactors: update the relevant docs in the same task, including `README.md`, `ARCHITECTURE.md`, `DESIGN_REFACTOR.md`, and domain-specific notes when behavior changes.

## Quick Start

```bash
python3 -m pokemon_price_scheduler run --config config/products.generated.json
```

Use a smaller test run while tuning sources:

```bash
python3 -m pokemon_price_scheduler run --config config/products.generated.json --limit 3
```

To add MiniMax-generated seller notes to the reports, set your API key and pass `--ai-summary`:

```bash
export MINIMAX_API_KEY="your-api-key"
python3 -m pokemon_price_scheduler run --config config/products.generated.json --limit 3 --ai-summary
```

The integration uses MiniMax's OpenAI-compatible chat endpoint. You can override the defaults with:

- `MINIMAX_MODEL` - defaults to `MiniMax-M2.7-highspeed`
- `MINIMAX_BASE_URL` - defaults to `https://api.minimax.io/v1`
- `MINIMAX_TIMEOUT_SECONDS` - defaults to `30`

Outputs:

- `reports/latest.md` - human-readable recommendation report
- `reports/latest.csv` - spreadsheet-friendly summary
- `reports/dashboard.html` - clickable dashboard with red/amber price-delta alerts
- `reports/cards/*.html` - card detail pages with identity, chart, and source listings
- `reports/opportunities.html` - first-pass local-supply/global-demand opportunity shortlist
- `reports/charts/*.svg` - per-card price history charts
- `data/price_history.sqlite3` - historical runs, source observations, and per-run price snapshots

## Configure Products

Edit `config/products.json`.

Each product can include:

- `title`: your Tokopedia title
- `own_price_idr`: your current price
- `tokopedia_url`: your listing URL
- `search_terms`: broad competitor search phrase; the first entry controls runtime Tokopedia, eBay sold, and SnkrDunk searches
- `sources`: optional custom reference URLs; stored marketplace search URLs are ignored for the built-in competitor searches

Titles containing words like `Japanese`, `JPN`, `JP`, `English`, or `ENG` are automatically tagged with language.

## Sync Tokopedia Store

```bash
python3 -m pokemon_price_scheduler sync-store --url "https://www.tokopedia.com/[store-name]/product?sort=10"
```

This tries to extract products from the public store page and writes `data/store_products.json`. Tokopedia changes its frontend often, so review the file before relying on it. You can then copy useful entries into `config/products.json`.

To create a runnable config from the synced store products:

```bash
python3 -m pokemon_price_scheduler seed-config --pokemon-only
```

This writes `config/products.generated.json` with initial search terms and marketplace sources for each Pokemon product. At runtime, both the scheduler and card-detail refresh rebuild Tokopedia competitor, eBay sold-listing, and SnkrDunk searches from `search_terms[0]`, so editing the card detail search term is the preferred way to broaden or narrow competitor discovery.

Initial searches are generated from parsed card identity instead of full listing titles. For example:

`Meowth Ex SAR 114/080 m3 - Munikis / Nihility Zero - Kartu Pokemon TCG Japanese`

becomes:

- `search_terms[0]`: `Meowth Ex SAR raw NM m3 Japanese`

The same phrase is used for Tokopedia, eBay sold listings, and SnkrDunk unless you edit it on the card detail page.

## Live App

Start the Flask app:

```bash
python3 -m pokemon_price_scheduler.web
```

The live app serves a single-page interface with:

- `/` - Dashboard with Live Store Signals, compact portfolio/market value KPIs, Active Cards preview, and Repricing Queue preview
- `/cards` - Store Listings AG Grid with current Tokopedia price, market average, delta, alert status, and trend
- `/cards/<slug>` - card detail with latest prices, 7-day and 30-day trend, suggested prices, chart, and price history table
- `/inventory` - owned inventory from opportunity conversions and listing lifecycles
- `/opportunities` - persistent buy-list opportunities with add and conversion workflow
- `/opportunities/<slug>` - opportunity detail and conversion action
- `/repricing` - daily Repricing Queue with action summaries, filters, sorting, suggested prices, and recommended action
- `/reports` - generated report links plus Source Health diagnostics from the latest scheduler trace
- `/soldcards` - sold listing review, sales income capture, and restock workflow

The frontend is a Flask-served SPA using Alpine.js, AG Grid Community, server-rendered HTML fragments, and a minimal retro handheld design system. AG Grid CSS and JavaScript are vendored under `static/vendor/ag-grid/` and loaded by `static/index.html`.

### Live App Navigation

The live app uses the same Flask shell for every navigation route, then fetches page fragments from `/api/*` endpoints:

- **Dashboard** - first-screen operating view. `Live Store Signals` wraps Active Listings, Portfolio Value, Market Value, Active Alerts, and Latest Run. Portfolio and market totals are compacted to `Rp x.xM` for dashboard scanning. Below the signals, compact Active Cards and Repricing Queue previews link to their full pages.
- **Store Listings** - full active-listing grid for Tokopedia listing management. This keeps full currency formatting and is separate from owned Inventory.
- **Inventory** - owned stock from buy-list conversions and listing lifecycles.
- **Opportunities** - persistent buy-list cards with source link, price, detail page, and conversion into inventory/listing.
- **Repricing Queue** - full pricing action workflow with summaries, filters, sorting, suggested prices, and recommended action.
- **Sold Cards** - sales review and income capture. Sold rows show listing price, sold price, bought price, sold date, and net income. Existing sold cards can be edited, and restocking creates a new active listing lifecycle while preserving sale history.
- **Reports** - generated report files plus Source Health. Source Health was moved here so dashboard space stays focused on store operation.

Menu icons are inline SVGs embedded in `static/index.html`; no icon library is required.

## Generated Dashboard

Open `reports/dashboard.html` in a browser after a run. Each row shows your Tokopedia price, global average, delta percentage, and alert level. Clicking a row opens a card detail page with:

- parsed card identity
- price history chart
- up to 10 nearby or same-item listings per source
- source warnings when a marketplace blocks scraping

## Price History and Repricing

Every scheduler run stores one `price_history` snapshot per card after prices are analyzed. Each snapshot records the card, Tokopedia price, market average, delta percent, alert status, source summary, and timestamp.

Suggested Tokopedia prices are derived from the latest market average:

- Quick Sale Price = `market_avg_price * 0.92`
- Normal Price = `market_avg_price * 0.98`
- Max Profit Price = `market_avg_price * 1.05`

If market average is missing, the app shows `Insufficient market data`.

The Repricing Queue recommends:

- `Lower price` when Tokopedia price is more than 10% above market average
- `Raise price` when Tokopedia price is more than 10% below market average
- `Missing market data` when market average is unavailable
- `Aligned` when price is within +/-10% of market average

## Inventory and Sales Tracking

The live app now has a proper inventory/sales layer in SQLite alongside the legacy product config.

- `config/products.json` still keeps the scheduler-compatible listing config and status flags.
- `data/price_history.sqlite3` now also stores `cards`, `listings`, and `sales` tables for inventory lifecycle and income analysis.
- Active cards are live Tokopedia listings.
- Sold cards are completed listing lifecycles with sale metadata.
- Restocking a sold card creates a new active listing lifecycle instead of overwriting the previous sale.

Manual sale capture is available from card detail and sold cards:

- **Mark Sold** on an active card requires sold date, sold price, bought price, and net income.
- **Edit Sale** on a sold card updates sold date, sold price, bought price, and net income.
- Net income is manually entered for now; sold price and bought price are stored separately so marketplace fee, profit, margin, and ROI calculations can be added later.

See `INVENTORY_SALES.md` for the detailed model, endpoints, and future extension notes.

## Opportunities and Inventory Conversion

The live `/opportunities` page is a buy-list workflow, not the generated market-opportunity report. Add cards you are considering buying with card name, rarity, language, source, link, and price. Clicking an opportunity opens `/opportunities/<slug>`.

From the opportunity detail page, **Convert to Inventory** always creates an owned inventory item. Bought price defaults to the opportunity price but can be edited. If Tokopedia listing URL and listing price are provided during conversion, the app also creates an active Store Listing in `config/products.json` and the SQLite listing lifecycle.

Converted opportunities are marked `converted` and kept for audit history.

`reports/opportunities.html` remains a static generated report output for local-supply/global-demand analysis, separate from the live buy-list page.

See `OPPORTUNITIES_INVENTORY.md` for the detailed workflow, conversion logic, schema notes, and compatibility checklist.

## Daily Schedule

On macOS/Linux cron, run:

```cron
0 9 * * * cd "/Users/[username]/Documents/pokemon-store-scheduler" && python3 -m pokemon_price_scheduler run --config config/products.generated.json >> data/cron.log 2>&1
```

The command is safe to run repeatedly; every run gets its own timestamped history.

## Notes About Sources

Some sites render prices with JavaScript, rate-limit scrapers, or require cookies. When a source cannot be parsed, the report records a warning instead of silently guessing.

Built-in competitor searches are generated at runtime from each product's first `search_terms` entry. The card detail page's search-term editor updates that value in `config/products.json`, and the next scheduler run or manual refresh uses it for Tokopedia, eBay sold listings, and SnkrDunk. If no search term is configured, the app falls back to the parsed card identity query and then the product title.

Tokopedia competitor results are filtered with a simple scam/outlier rule: if there are enough results, prices far below the median are ignored before comparing your listing.

The final analysis also ignores parsed prices that are implausibly far from your own listing price. Tune these in `config/products.json`:

- `comparable_min_ratio_to_own`
- `comparable_max_ratio_to_own`

## Architecture

```
pokemon_price_scheduler/
├── domain/                    # Pure business logic — no I/O, fully testable
│   ├── models.py             # Product, Source, PriceObservation, ProductAnalysis, alert_label()
│   ├── analysis.py           # analyze_product(), score_observations(), relevance_score()
│   ├── card_parser.py        # parse_card_identity(), CardIdentity
│   └── text.py               # clean_text() utility
│
├── infrastructure/            # External I/O concerns
│   ├── http.py               # HTTP fetching with gzip/retry
│   ├── parsing.py            # Price extraction, JSON walking, outlier rejection
│   ├── scrapers.py           # MarketplaceScraper + per-marketplace extractors
│   ├── history.py            # SQLite persistence layer
│   ├── ai.py                 # MiniMax LLM client
│   └── reports.py            # Composable ReportEngine (see below)
│
├── templates/                 # Jinja2 HTML templates
│   ├── base.html             # Shared shell (sidebar, topbar, CSS design tokens, JS)
│   ├── dashboard.html
│   ├── card_detail.html
│   └── opportunities.html
│
├── v2/                         # Run trace storage and newer pipeline persistence
├── static/vendor/ag-grid/      # Vendored AG Grid Community runtime and theme assets
├── ui_components.py            # Shared live-app HTML/AG Grid component builders
├── inventory.py                # SQLite cards/listings/sales/opportunities/inventory tracking
├── models.py                  # Backward-compat shim → re-exports domain/
├── parsing.py                 # Backward-compat shim → re-exports infrastructure/
├── http.py                    # Backward-compat shim → re-exports infrastructure/
├── scrapers.py                # Backward-compat shim → re-exports infrastructure/
├── history.py                 # Backward-compat shim → re-exports infrastructure/
├── ai.py                      # Backward-compat shim → re-exports infrastructure/
├── reports.py                 # Backward-compat shim → re-exports infrastructure/
├── analyze.py                 # Backward-compat shim → re-exports domain/
├── card_parser.py             # Backward-compat shim → re-exports domain/
└── web.py                     # Flask SPA + HTMX-style API endpoints
```

### Domain Layer (`domain/`)

Pure functions and frozen dataclasses with no imports to any infrastructure code. The `domain/models.py` types (`Product`, `Source`, `PriceObservation`, `SourceResult`, `ProductAnalysis`) are the central schema of the entire application. All analysis logic lives in `domain/analysis.py` and can be unit-tested without spinning up servers or hitting the network.

### Infrastructure Layer (`infrastructure/`)

Handles all external I/O: HTTP fetching, marketplace scraping, SQLite persistence, and LLM calls. Each module has a single responsibility. No infrastructure code imports from another infrastructure module — `infrastructure/scrapers.py` imports from `infrastructure/http.py` and `infrastructure/parsing.py`, but not from `infrastructure/history.py` or `infrastructure/ai.py`.

### Report Engine (`infrastructure/reports.py`)

Uses a `Report` abstract base class. Concrete implementations are:

| Class | Output |
|---|---|
| `MarkdownReport` | `reports/latest.md` |
| `CSVReport` | `reports/latest.csv` |
| `SVGSummaryReport` | `reports/charts/*.svg` |
| `CardDetailReport` | `reports/cards/*.html` |
| `DashboardReport` | `reports/dashboard.html` |
| `OpportunitiesReport` | `reports/opportunities.html` |

`ReportEngine` orchestrates them all, but each `Report` can also be instantiated and run independently. To generate only one report type during development:

```python
from pokemon_price_scheduler.infrastructure.reports import CardDetailReport, ReportEngine
CardDetailReport().render(analyses, run_id)
```

### Template-Based Frontend (`templates/`)

Generated HTML uses Jinja2 templates instead of Python string interpolation. `base.html` contains the shared layout, sidebar, CSS design tokens, and client-side JS. `dashboard.html`, `card_detail.html`, and `opportunities.html` extend it via `{% block body %}`. The `templates/renderers.py` functions prepare data dictionaries and call `template.render()`.

### Backward-Compatibility Shims

All root-level modules (`models.py`, `scrapers.py`, `history.py`, etc.) are shims that re-export from the new layered packages. Existing import paths throughout the codebase — in `cli.py`, `web.py`, and the test suite — continue to work without changes.
