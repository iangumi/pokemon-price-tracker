# Pokemon Store Price Scheduler

This tool checks your Tokopedia Pokemon card listings at or above Rp 500,000 against marketplace references, stores each run in SQLite, and helps you decide which cards need repricing.

It is designed to run both on demand and from a daily schedule.

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
- `search_terms`: search phrases to use for matching
- `sources`: reference URLs to check

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

This writes `config/products.generated.json` with Tokopedia competitor, eBay sold-listing, and SnkrDunk searches for each Pokemon product. Add exact SnkrDunk/Collectr URLs manually for high-value cards when available.

Searches are generated from parsed card identity instead of full listing titles. For example:

`Meowth Ex SAR 114/080 m3 - Munikis / Nihility Zero - Kartu Pokemon TCG Japanese`

becomes:

- Tokopedia/eBay: `Meowth Ex SAR raw NM m3 Japanese`
- SnkrDunk: `Meowth Ex SAR m3`

## Live App

Start the Flask app:

```bash
python3 -m pokemon_price_scheduler.web
```

The live app serves a single-page interface with:

- `/cards` - My Cards AG Grid with current Tokopedia price, market average, delta, alert status, and trend
- `/cards/<slug>` - card detail with latest prices, 7-day and 30-day trend, suggested prices, chart, and price history table
- `/repricing` - daily Repricing Queue with action summaries, filters, sorting, suggested prices, and recommended action
- `/opportunities` - local-supply/global-demand opportunity shortlist
- `/soldcards` - sold listing review and restore workflow

The frontend is a Flask-served SPA using Alpine.js and AG Grid Community. AG Grid CSS and JavaScript are vendored under `static/vendor/ag-grid/` and loaded by `static/index.html`.

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

## Opportunity Discovery

`reports/opportunities.html` is a first-pass shortlist for cards where global evidence exists but local Tokopedia supply appears thin. This is meant for review before buying, not automatic purchasing.

## Daily Schedule

On macOS/Linux cron, run:

```cron
0 9 * * * cd "/Users/[username]/Documents/pokemon-store-scheduler" && python3 -m pokemon_price_scheduler run --config config/products.generated.json >> data/cron.log 2>&1
```

The command is safe to run repeatedly; every run gets its own timestamped history.

## Notes About Sources

Some sites render prices with JavaScript, rate-limit scrapers, or require cookies. When a source cannot be parsed, the report records a warning instead of silently guessing.

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
