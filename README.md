# Pokemon Store Manager

A local Flask web app for running a Pokemon TCG store on Tokopedia. The site tracks active listings, compares them against marketplace prices, queues repricing work, records sold cards, and manages buy-list opportunities and owned inventory.

The app is built for daily store operation first. Static reports and CLI commands still exist, but the main workflow is the website.

## Start The Website

```bash
python3 -m pokemon_price_scheduler.web
```

Open:

```text
http://localhost:5001
```

The app serves a single-page interface from Flask. Navigation routes such as `/cards`, `/repricing`, and `/soldcards` load the same shell, then fetch page fragments from `/api/*`.

## What You Can Do In The Website

### Dashboard

Route: `/`

Use Dashboard as the first-screen operating view:

- See active listing count, portfolio value, market value, active alerts, and latest scheduler run.
- Preview highest-value active cards.
- Preview repricing work that needs attention.
- Start a full scheduler run from the top action button.

### Store Listings

Route: `/cards`

Use Store Listings for active Tokopedia listing review:

- View active cards in an AG Grid table.
- Compare your Tokopedia price with latest market average.
- Review price delta, alert status, and trend.
- Open a card detail page for deeper evidence.
- Add a new active card.
- Sync active products from your Tokopedia store.

### Card Detail

Route: `/cards/<slug>`

Use Card Detail for one-card pricing decisions:

- Review latest Tokopedia price, market average, delta, 7-day trend, and 30-day trend.
- See suggested prices:
  - Quick Sale Price = `market_avg_price * 0.92`
  - Normal Price = `market_avg_price * 0.98`
  - Max Profit Price = `market_avg_price * 1.05`
- Edit the card search term.
- Refresh competitors for that card only.
- Generate cached AI repricing advice from current pricing evidence.
- Refresh and review international counterpart candidates with raw currency and converted IDR prices.
- Update the current Tokopedia listing price from the product page.
- Review price history and source evidence. Source Evidence shows the normalized IDR price used for analysis and, for non-IDR sources such as SnkrDunk, the original raw marketplace amount.
- Mark an active card sold.
- Edit sale details for a sold card.

The card search term is important: `search_terms[0]` is the broad competitor query used for Tokopedia, eBay sold listings, and SnkrDunk during both full scheduler runs and single-card refreshes.

AI advice is generated on demand and cached by the exact evidence input. If the evidence has not changed, the app reuses the cached advice instead of calling the AI again. SnkrDunk source observations are converted from JPY to IDR with deterministic fixed FX before market calculations. Counterpart refresh uses already collected source observations and the same fixed FX approach; it does not fetch live exchange rates.

### Repricing Queue

Route: `/repricing`

Use Repricing Queue as the daily pricing workflow:

- Review cards grouped by recommended action.
- Filter by `Lower price`, `Raise price`, `Missing market data`, or `Aligned`.
- Sort by priority, delta, price, title, or latest run data.
- Use suggested prices to decide the next Tokopedia price.

The queue recommends:

- `Lower price` when your listing is more than 10% above market average.
- `Raise price` when your listing is more than 10% below market average.
- `Missing market data` when no reliable market average exists, including active cards that have not appeared in scheduler price-history results yet.
- `Aligned` when your price is within +/-10% of market average.

### Inventory

Route: `/inventory`

Use Inventory to review owned stock separately from active Tokopedia listings:

- See active listed stock.
- See inventory created from opportunities.
- Keep inventory-only purchases out of Store Listings and Repricing Queue until they are listed.
- Active Tokopedia listing rows are synced from active product config, so stale active SQLite listing rows are removed when the product is no longer active in config.

### Opportunities

Routes: `/opportunities`, `/opportunities/<slug>`

Use Opportunities as a persistent buy-list:

- Add cards you are considering buying.
- Store source, source link, rarity, language, and observed buy price.
- Open an opportunity detail page.
- Convert an opportunity into owned inventory.
- Optionally create an active Store Listing during conversion by providing Tokopedia URL and listing price.

Conversion behavior:

- Bought price only creates inventory. It appears on `/inventory`, not `/cards` or `/repricing`.
- Bought price plus Tokopedia URL and listing price creates inventory and an active listing. It appears on `/inventory`, `/cards`, and `/repricing`.
- Converted opportunities remain visible for audit history.

### Sold Cards

Route: `/soldcards`

Use Sold Cards for sales and income tracking:

- Review completed listing lifecycles in a searchable sales ledger.
- Filter the ledger by complete or missing sale data, and by common sale periods.
- Page through larger sales history with AG Grid pagination.
- Record sold date, sold price, bought price, and net income.
- Preview marketplace fee amount and percentage in the sale modal from sold price minus net income/settlement.
- Edit existing sale details.
- Use `Restore Active` when a card was marked sold by mistake. This removes the sold snapshot and sale income record, then returns the same listing to Store Listings.
- Use `Restock as New` when the card really sold and you have another copy. This keeps the sale history and creates a new active listing lifecycle.

Restocking creates a new active listing lifecycle and preserves the old sale record. Restoring active is an undo/correction flow and removes the sale from Sold Cards and income totals.

Rows are marked `Complete` only when sold date, sold price, bought price, and net income are all present. Rows missing any of those values remain visible as `Missing sale data` so old sold snapshots can be backfilled.

### Reports

Route: `/reports`

Use Reports for generated files and source diagnostics:

- Open `latest.md` and `latest.csv`.
- Review Source Health for the latest scheduler trace.
- Debug marketplace failures without cluttering the Dashboard.

## Scheduler And Competitor Refresh

The website has two pricing refresh paths:

- **Run Scheduler** starts the full CLI scheduler in a subprocess and streams status through `/run/status`.
- **Refresh Competitors** on Card Detail refreshes one card in a background thread.

Both paths use the same competitor search rule:

1. Use `Product.search_terms[0]`.
2. If missing, fall back to parsed card identity.
3. If parsing cannot produce a query, fall back to the product title.

Runtime-generated competitor sources:

- Tokopedia: `https://www.tokopedia.com/find/<search-term-slug>`
- eBay sold listings: `https://www.ebay.com/sch/i.html?_nkw=<search-term>&LH_Sold=1&LH_Complete=1`
- SnkrDunk: `https://snkrdunk.com/v3/search?...&keyword=<search-term>...`

Stored marketplace search URLs in `config/products.json` are treated as stale snapshots for built-in competitor searches. Unknown or custom source kinds are still preserved.

## Data Files

Main files and directories:

- `config/products.json` - active/sold product config used by the website and scheduler.
- `data/price_history.sqlite3` - runs, observations, source fetches, price history, inventory, opportunities, listings, and sales.
- `ai_repricing_advice` table - cached Card Detail AI advice keyed by card and evidence hash.
- `counterpart_candidates` table - international counterpart evidence with raw currency, converted IDR price, and match confidence.
- `observations` table - scraped marketplace evidence with normalized IDR price, source currency, raw price, match score, and comparable/excluded status.
- `data/scheduler.log` - background scheduler output from the website.
- `data/card-images/` - cached Tokopedia product images.
- `reports/latest.md` - latest Markdown report.
- `reports/latest.csv` - latest CSV report.
- `reports/charts/*.svg` - generated price charts.

## Product Config

Most product changes should happen through the website, but `config/products.json` remains the scheduler-compatible source for active listings.

Important product fields:

- `title` - Tokopedia product title.
- `own_price_idr` - current listing price.
- `tokopedia_url` - your own listing URL.
- `search_terms` - broad competitor query; first item controls built-in marketplace searches.
- `sources` - optional custom sources. Built-in marketplace search URLs are regenerated at runtime.
- `status` - `active` or `sold`.
- `sold_at` - sold timestamp/date for sold products.
- `added_at` - listing creation/import date when known.

## Useful CLI Commands

Start the web app:

```bash
python3 -m pokemon_price_scheduler.web
```

Run the full scheduler manually:

```bash
python3 -m pokemon_price_scheduler run --config config/products.json
```

Run a smaller scheduler sample:

```bash
python3 -m pokemon_price_scheduler run --config config/products.json --limit 3
```

Inspect the latest run trace:

```bash
python3 -m pokemon_price_scheduler inspect-run
```

Validate product config:

```bash
python3 -m pokemon_price_scheduler validate-config --config config/products.json
```

Sync Tokopedia store products to a review file:

```bash
python3 -m pokemon_price_scheduler sync-store --url "https://www.tokopedia.com/[store-name]/product?sort=10"
```

Seed a generated config from synced store products:

```bash
python3 -m pokemon_price_scheduler seed-config --pokemon-only
```

## Optional AI Features

The website can generate Card Detail AI Repricing Copilot advice when `MINIMAX_API_KEY` is set. The MiniMax client reads exported environment variables and the nearest project `.env` file, with exported values taking precedence. Scheduler runs can also attach MiniMax-generated seller notes when run from CLI:

```bash
export MINIMAX_API_KEY="your-api-key"
python3 -m pokemon_price_scheduler run --config config/products.json --limit 3 --ai-summary
```

Environment overrides:

- `MINIMAX_MODEL` - defaults to `MiniMax-M2.7-highspeed`
- `MINIMAX_BASE_URL` - defaults to `https://api.minimax.io/v1`
- `MINIMAX_TIMEOUT_SECONDS` - defaults to `30`

Card Detail AI advice is cached by card slug and evidence hash. Use `POST /api/cards/<slug>/ai-repricing-advice?force=1` to intentionally regenerate advice for unchanged evidence, for example after changing the AI prompt or token budget. The response remains non-fatal on missing API key or model failure and the page continues to show raw price evidence.

Counterpart candidates are rebuilt with `POST /api/cards/<slug>/counterparts/refresh` from stored observations for that card. Use this after a scheduler run or single-card competitor refresh when new observations exist.

See `AI_ROADMAP.md` for planned AI features and the rule that AI should explain fetched evidence, not invent prices.

## Daily Schedule

On macOS/Linux cron:

```cron
0 9 * * * cd "/Users/[username]/Documents/pokemon-store-scheduler" && python3 -m pokemon_price_scheduler run --config config/products.json >> data/cron.log 2>&1
```

Every run stores a new run trace and updates price history snapshots.

## Source And Pricing Notes

Some marketplaces render prices with JavaScript, rate-limit scraping, or require cookies. Source failures are recorded as warnings instead of guessed prices.

Filtering rules:

- Tokopedia low-price outliers can be marked as scam/noise.
- Prices far outside your own listing price range are ignored by comparable-ratio filters.
- Relevance scoring prefers listings that match card name, set symbol, rarity, and condition.

Tune comparable filters in `config/products.json`:

- `comparable_min_ratio_to_own`
- `comparable_max_ratio_to_own`

## Developer Notes

Core implementation files:

- `pokemon_price_scheduler/web.py` - Flask SPA routes, API endpoints, scheduler subprocess, card refresh.
- `pokemon_price_scheduler/ui_components.py` - server-rendered page fragments and AG Grid configuration.
- `static/index.html` - SPA shell, navigation, Alpine state, AG Grid adapter, modals, styles.
- `pokemon_price_scheduler/infrastructure/marketplace_sources.py` - runtime competitor source generation.
- `pokemon_price_scheduler/v2/pipeline.py` - traced scheduler pipeline.
- `pokemon_price_scheduler/infrastructure/scrapers.py` - marketplace scraping/parsing.
- `pokemon_price_scheduler/infrastructure/history.py` - price history persistence.
- `pokemon_price_scheduler/inventory.py` - inventory, opportunities, listings, and sales persistence.

Run tests:

```bash
python3 -m unittest discover -s tests
```

If `pytest` is installed, the unittest suite is pytest-compatible.
