# Live App Design Refactor

## Goals

- Make the live Flask app easier to use for pricing decisions and source debugging.
- Standardize the UI vocabulary across Dashboard, My Cards, Card Detail, Repricing Queue, Sold Cards, and Opportunities.
- Preserve the current Flask + Alpine architecture and existing routes while replacing ad-hoc table rendering with AG Grid.
- Make Repricing Queue usable as a daily workflow page with action summaries, filters, sorting, and suggested prices.

## Design Direction

The live app now uses a compact trading-desk direction: dark graphite surfaces, cyan operational accents, green/amber/red decision states, dense tables, and reusable evidence panels.

## Component Vocabulary

- `toolbar` for page-level actions.
- `metric-grid` and `metric-card` for KPIs and card-level pricing facts.
- `panel` for titled page sections.
- `table-shell`, `grid-shell`, and `ag-grid-host` for all tabular evidence.
- `cards-data-grid` for the My Cards AG Grid host.
- `repricing-controls` and `control-group` for Repricing Queue filter/sort controls.
- `status-badge` for alert, source, and run-state labels.
- `field-row`, `field-control`, and `input` for editable controls.
- `empty-state` for no-data and loading-style messages.
- `product-card` for sold-card tiles.

## Page Decisions

- Dashboard surfaces latest run health and source failures instead of only portfolio totals.
- My Cards emphasizes pricing decisions: own price, market average, delta, alert, and trend.
- Card Detail standardizes actions, search-term editing, metrics, identity, chart, and source evidence.
- Repricing Queue is the daily workflow surface: it summarizes Lower price, Raise price, Missing market data, and Aligned cards, then lets the user filter and sort the actionable queue.
- Sold Cards reuses the same card/action language as active cards.
- Opportunities remains a review queue, not a buy recommendation engine.

## AG Grid Migration

- AG Grid Community assets are vendored under `static/vendor/ag-grid/` so the app does not depend on CDN availability at runtime.
- `pokemon_price_scheduler.ui_components.data_table()` now emits a debuggable AG Grid mount with `data-columns` and `data-rows` JSON attributes.
- Columns that are empty for every row are omitted before rendering, so the grid does not fetch or show consistently blank fields.
- `static/index.html` owns a single AG Grid adapter that initializes every fetched fragment, applies `themeQuartz.withPart(colorSchemeDarkBlue)`, destroys old grid instances before navigation, and maps named renderers/formatters to reusable badge, link, IDR, percent, and trend cells.
- `window._agGridById` stores grid APIs by `data-grid-id` so page controls can use AG Grid-native filtering and sorting.
- Repricing Queue uses `filterRepricing(action)` and `sortRepricing(mode)` instead of DOM table manipulation.
- App wrapper classes must not start with `ag-`; AG Grid theme CSS owns that prefix. Use `grid-shell`, `cards-data-grid`, and `ag-grid-host`.
- DataTables and jQuery table initialization have been removed from the live page.

## Phase 1 Pricing Features

- Scheduler runs now store one `price_history` snapshot per card with Tokopedia price, market average, delta percent, alert status, source summary, and timestamp.
- Card Detail shows latest Tokopedia price, latest market average, 7-day and 30-day trend, suggested prices, a simple price chart, and a history table.
- Suggested prices are calculated from market average: Quick Sale at 92%, Normal at 98%, and Max Profit at 105%.
- Repricing Queue classifies cards as Lower price, Raise price, Missing market data, or Aligned using the +/-10% market-delta rule.

## Verification Checklist

- `python3 -m unittest discover -s tests`
- `python3 -m compileall -q pokemon_price_scheduler tests`
- Open `http://localhost:5001` after `flask-restart`.
- Check Dashboard, My Cards, Card Detail, Repricing Queue, Sold Cards, and Opportunities.
- Confirm AG Grid sorting/filtering/pagination work on My Cards, Source Evidence, and Repricing Queue.
- Confirm Repricing Queue summary counts, action filters, and sort controls update the grid correctly.
- Trigger scheduler and single-card refresh; buttons should disable/show progress.
- Confirm source failures render as status badges on Dashboard.
