# Live App Frontend Refactor Notes

## Goals

- Make the live Flask app easier to use for pricing decisions and source debugging.
- Standardize the UI vocabulary across Dashboard, My Cards, Card Detail, Repricing Queue, Sold Cards, and Opportunities.
- Preserve the current Flask + Alpine architecture and existing routes while replacing ad-hoc table rendering with AG Grid.
- Make Repricing Queue usable as a daily workflow page with action summaries, filters, sorting, and suggested prices.
- Keep future frontend refactors reproducible by documenting the current navigation, data flow, component vocabulary, and visual rules.

## Design Direction

The live app now uses a minimal retro handheld direction: LCD-green panels, cream case surfaces, black pixel borders, square controls, compact monospace labels, inline SVG icons, and dense but readable data tables.

The design should feel like an operational dashboard running on a retro handheld, not a marketing page. Avoid oversized heroes, decorative gradients, rounded card-heavy layouts, or ornamental backgrounds. Use the existing LCD panel treatment and compact table/card language.

## Current Navigation Structure

- **Dashboard** (`/`, `/api/dashboard`) - first-screen store operations view.
  - `Live Store Signals` wraps Active Listings, Portfolio Value, Market Value, Active Alerts, and Latest Run.
  - Portfolio and market totals use compact `Rp x.xM` formatting only on dashboard KPIs.
  - `Active Cards` preview shows highest-value active Tokopedia listings.
  - `Repricing Queue` preview shows actionable pricing work first.
- **My Cards** (`/cards`, `/api/cards`) - full AG Grid inventory review.
- **Reports** (`/reports`, `/api/reports`) - generated report links and Source Health diagnostics.
- **Opportunities** (`/opportunities`, `/api/opportunities`) - first-pass buying/import review queue.
- **Repricing Queue** (`/repricing`, `/api/repricing`) - full daily pricing action workflow.
- **Sold Cards** (`/soldcards`, `/api/soldcards`) - sold/delisted listing review and restore workflow.

Source Health intentionally lives in Reports, not Dashboard. Dashboard should stay focused on live store signals and immediate pricing work.

## Component Vocabulary

- `toolbar` for page-level actions.
- `metric-grid` and `metric-card` for KPIs and card-level pricing facts.
- `ui-icon` and `nav-icon` for inline SVG icons. Do not add an icon dependency unless the project intentionally moves to a bundled frontend build.
- `panel` for titled page sections.
- `table-shell`, `grid-shell`, and `ag-grid-host` for all tabular evidence.
- `cards-data-grid` for the My Cards AG Grid host.
- `dashboard-preview-grid` and `dashboard-preview-table` for compact dashboard previews.
- `repricing-controls` and `control-group` for Repricing Queue filter/sort controls.
- `status-badge` for alert, source, and run-state labels.
- `field-row`, `field-control`, and `input` for editable controls.
- `empty-state` for no-data and loading-style messages.
- `product-card` for sold-card tiles.

## Page Decisions

- Dashboard surfaces Live Store Signals, Active Cards preview, and Repricing Queue preview. It does not render Source Health.
- My Cards emphasizes pricing decisions: own price, market average, delta, alert, and trend.
- Reports owns Source Health and generated report links (`latest.md`, `latest.csv`).
- Card Detail is a price-review page: action toolbar, search-term editor, Price Review Snapshot, chart/history, suggested prices, identity, and source evidence.
- Repricing Queue is the daily workflow surface: it summarizes Lower price, Raise price, Missing market data, and Aligned cards, then lets the user filter and sort the actionable queue.
- Sold Cards reuses the same card/action language as active cards.
- Opportunities remains a review queue, not a buy recommendation engine.

## Dashboard Data Rules

- Active Listings count comes from active Tokopedia products only.
- Portfolio Value sums active listing `own_price_idr`.
- Market Value sums available latest global averages for active listings.
- Active Alerts count only red alert rows.
- Active Cards preview sorts active listings by Tokopedia price descending.
- Repricing preview uses `repricing_queue(active_slugs)` and prioritizes Lower price, Raise price, Missing market data, then Aligned.
- Dashboard KPI money values use `compact_millions()` (`Rp 124.2M`). Tables and detail pages keep full `idr()` formatting.

## Card Detail Review Rules

- Keep latest snapshot metrics above the fold: latest Tokopedia price, latest market average, delta, 7-day trend, 30-day trend, and status.
- Show the graph/history section before secondary identity/source evidence so pricing review is the primary task.
- Handle missing market average safely: show `-` for missing latest market average and `Insufficient market data` for suggested prices.
- Keep source evidence available below the price-review sections for debugging scraper decisions.

## AG Grid Migration

- AG Grid Community assets are vendored under `static/vendor/ag-grid/` so the app does not depend on CDN availability at runtime.
- `pokemon_price_scheduler.ui_components.data_table()` now emits a debuggable AG Grid mount with `data-columns` and `data-rows` JSON attributes.
- Columns that are empty for every row are omitted before rendering, so the grid does not fetch or show consistently blank fields.
- `static/index.html` owns a single AG Grid adapter that initializes every fetched fragment, applies `themeQuartz.withPart(colorSchemeDarkBlue)`, destroys old grid instances before navigation, and maps named renderers/formatters to reusable badge, link, IDR, percent, and trend cells.
- `window._agGridById` stores grid APIs by `data-grid-id` so page controls can use AG Grid-native filtering and sorting.
- Repricing Queue uses `filterRepricing(action)` and `sortRepricing(mode)` instead of DOM table manipulation.
- App wrapper classes must not start with `ag-`; AG Grid theme CSS owns that prefix. Use `grid-shell`, `cards-data-grid`, and `ag-grid-host`.
- DataTables and jQuery table initialization have been removed from the live page.

## Retro Implementation Rules

- Keep the live app in Flask + Alpine + AG Grid. Do not introduce React or a frontend build unless explicitly planned.
- Put reusable server-rendered UI in `pokemon_price_scheduler/ui_components.py`; keep the SPA shell, navigation, AG Grid adapter, and global CSS in `static/index.html`.
- Use inline SVGs for menu and KPI icons. Keep icons stroke-only, square-ended, and sized through `.nav-icon`/`.ui-icon`.
- Avoid nested cards. Use `panel` for sections, `metric-card` for KPI tiles, and simple preview tables for compact dashboard data.
- For dense pages, prefer AG Grid. For dashboard previews, prefer simple tables with fewer columns so the first screen stays readable.
- Preserve color semantics: green/success for aligned or OK, amber/warning for raise/missing caution, red/danger for lower-price/over-market action.
- On mobile, navigation stacks first, then content; preview sections should stack to one column and keep horizontal scroll only when unavoidable.

## Phase 1 Pricing Features

- Scheduler runs now store one `price_history` snapshot per card with Tokopedia price, market average, delta percent, alert status, source summary, and timestamp.
- Card Detail shows latest Tokopedia price, latest market average, 7-day and 30-day trend, suggested prices, a simple price chart, and a history table.
- Suggested prices are calculated from market average: Quick Sale at 92%, Normal at 98%, and Max Profit at 105%.
- Repricing Queue classifies cards as Lower price, Raise price, Missing market data, or Aligned using the +/-10% market-delta rule.

## Verification Checklist

- `python3 -m unittest discover -s tests`
- `python3 -m compileall -q pokemon_price_scheduler tests`
- Start the live app with `flask --app pokemon_price_scheduler.web run --host 127.0.0.1 --port 5010` or the local project restart workflow.
- Check Dashboard, My Cards, Reports, Card Detail, Repricing Queue, Sold Cards, and Opportunities.
- On Dashboard, confirm Live Store Signals, Active Cards preview, Repricing Queue preview, compact `Rp x.xM` KPI values, and inline SVG menu icons.
- On Reports, confirm Source Health renders there and not on Dashboard.
- Confirm AG Grid sorting/filtering/pagination work on My Cards, Source Evidence, and Repricing Queue.
- Confirm Repricing Queue summary counts, action filters, and sort controls update the grid correctly.
- Trigger scheduler and single-card refresh; buttons should disable/show progress.
- Confirm source failures render as status badges on Reports.
