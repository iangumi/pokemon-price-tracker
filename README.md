# Pokemon Store Price Scheduler

This tool checks your Tokopedia Pokemon card listings at or above Rp 500,000 against marketplace references, stores each run in SQLite, and generates a report showing cards that look underpriced.

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
- `data/price_history.sqlite3` - historical runs and source observations

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

## Dashboard

Open `reports/dashboard.html` in a browser after a run. Each row shows your Tokopedia price, global average, delta percentage, and alert level. Clicking a row opens a card detail page with:

- parsed card identity
- price history chart
- up to 10 nearby or same-item listings per source
- source warnings when a marketplace blocks scraping

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
