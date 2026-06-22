# Live App Frontend Refactor Notes

## Goals

- Make the live Flask app easier to use for pricing decisions and source debugging.
- Standardize the UI vocabulary across Dashboard, Store Listings, Inventory, Card Detail, Repricing Queue, Sold Cards, and Opportunities.
- Preserve the current Flask + Alpine architecture and existing routes while replacing ad-hoc table rendering with AG Grid.
- Make Repricing Queue usable as a daily workflow page with action summaries, filters, sorting, and suggested prices.
- Keep future frontend refactors reproducible by documenting the current navigation, data flow, component vocabulary, and visual rules.

For major frontend changes, follow `AGENTS.md`: update this document in the same task when navigation, page decisions, visual rules, component vocabulary, modals, AG Grid behavior, or verification steps change.

## Design Direction

The live app now uses a minimal retro handheld direction: LCD-green panels, cream case surfaces, black pixel borders, square controls, compact monospace labels, inline SVG icons, and dense but readable data tables.

The design should feel like an operational dashboard running on a retro handheld, not a marketing page. Avoid oversized heroes, decorative gradients, rounded card-heavy layouts, or ornamental backgrounds. Use the existing LCD panel treatment and compact table/card language.

## Current Navigation Structure

- **Dashboard** (`/`, `/api/dashboard`) - first-screen store operations view.
  - `Live Store Signals` wraps Active Listings, Portfolio Value, Market Value, Active Alerts, and Latest Run.
  - Portfolio and market totals use compact `Rp x.xM` formatting only on dashboard KPIs.
  - `Active Cards` preview shows highest-value active Tokopedia listings.
  - `Repricing Queue` preview shows actionable pricing work first.
- **Store Listings** (`/cards`, `/api/cards`) - full AG Grid active Tokopedia listing review.
- **Inventory** (`/inventory`, `/api/inventory`) - owned stock from buy-list conversions and listing lifecycles.
- **Opportunities** (`/opportunities`, `/api/opportunities`) - persistent buy-list cards with add, detail, and conversion workflow.
- **Repricing Queue** (`/repricing`, `/api/repricing`) - full daily pricing action workflow.
- **Sold Cards** (`/soldcards`, `/api/soldcards`) - sales review and income capture. It shows completed listing lifecycles in an AG Grid sales ledger with sold price, bought price, sold date, net income, quality status, filters, pagination, and row actions.
- **Reports** (`/reports`, `/api/reports`) - generated report links and Source Health diagnostics.

Source Health intentionally lives in Reports, not Dashboard. Dashboard should stay focused on live store signals and immediate pricing work.

## Component Vocabulary

- `toolbar` for page-level actions.
- `metric-grid` and `metric-card` for KPIs and card-level pricing facts.
- `ui-icon` and `nav-icon` for inline SVG icons. Do not add an icon dependency unless the project intentionally moves to a bundled frontend build.
- `panel` for titled page sections.
- `table-shell`, `grid-shell`, and `ag-grid-host` for all tabular evidence.
- `cards-data-grid` for the Store Listings AG Grid host.
- `dashboard-preview-grid` and `dashboard-preview-table` for compact dashboard previews.
- `repricing-controls` and `control-group` for Repricing Queue filter/sort controls.
- `status-badge` for alert, source, and run-state labels.
- `field-row`, `field-control`, and `input` for editable controls.
- `empty-state` for no-data and loading-style messages.
- `product-card` for card-style surfaces where a dense grid is not better.
- `opportunityLink` AG Grid renderer for opportunity detail links.
- `statusBadge` AG Grid renderer for opportunity status and reusable state labels.

## Page Decisions

- Dashboard surfaces Live Store Signals, Active Cards preview, and Repricing Queue preview. It does not render Source Health.
- Store Listings emphasizes pricing decisions: own price, market average, delta, alert, and trend.
- Reports owns Source Health and generated report links (`latest.md`, `latest.csv`).
- Card Detail is a price-review page: action toolbar, search-term editor, Price Review Snapshot, AI decision support, identity, chart/history, suggested prices, and source evidence.
- Card Detail also owns the V1 AI workflow: AI Repricing Copilot and International Counterparts panels sit near the price snapshot because they explain the current pricing decision.
- Repricing Queue is the daily workflow surface: it summarizes Lower price, Raise price, Missing market data, and Aligned cards, then lets the user filter and sort the actionable queue. It includes every active Store Listing, even when a card has no latest scheduler result yet.
- Sold Cards is a sales ledger. The page starts with `Sales Summary`, then an AG Grid table with listing price, sold price, bought price, sold date, net income, quality status, `Edit Sale`, `Restore Active`, and `Restock as New` actions.
- Inventory is the owned-stock surface. It combines active listings, sold listing lifecycles, and opportunity conversions so stock can be reviewed separately from scheduler-visible listings.
- Opportunities is a buy-list workflow. It stores real candidate cards, supports a detail route, and converts candidates into owned inventory or Store Listings when purchased.
- The generated `reports/opportunities.html` remains a separate static discovery report and should not be treated as the live buy-list source.

## Dashboard Data Rules

- Active Listings count comes from active Tokopedia products only.
- Portfolio Value sums active listing `own_price_idr`.
- Market Value sums available latest global averages for active listings.
- Active Alerts count only red alert rows.
- Active Cards preview sorts active listings by Tokopedia price descending.
- Repricing preview uses the same active-product row builder as the full Repricing Queue and prioritizes Lower price, Raise price, Missing market data, then Aligned.
- Dashboard KPI money values use `compact_millions()` (`Rp 124.2M`). Tables and detail pages keep full `idr()` formatting.

## Card Detail Review Rules

- Keep latest snapshot metrics above the fold: latest Tokopedia price, latest market average, delta, 7-day trend, 30-day trend, and status.
- Show AI Repricing Copilot and International Counterparts immediately after the latest price snapshot so decision support is visible without hiding raw evidence.
- Keep identity, graph/history, suggested prices, and source evidence in the lower evidence stack.
- Handle missing market average safely: show `-` for missing latest market average and `Insufficient market data` for suggested prices.
- Keep source evidence available below the price-review sections for debugging scraper decisions.
- AI advice must be generated by explicit user action, not automatically on page load.
- Counterpart rows must show raw price/currency, converted IDR, confidence, and match reason.
- Source Evidence rows must show the normalized IDR price used for analysis. When the source reported a foreign-currency amount, show the original raw amount under the IDR price.
- Source Evidence uses source-specific retro badge colors: Tokopedia green, SnkrDunk gray, eBay blue, and muted default for custom/unknown sources.
- Source Evidence uses `Match` instead of `Decision`. The column shows the relevance score plus `Comparable` or `Excluded`, which gives a clearer action signal than a vague decision label.
- Active card details include `Mark Sold`.
- Sold card details include `Edit Sale`.
- Sold Cards must separate correction from restock: `Restore Active` removes the sold snapshot and sale income, while `Restock as New` preserves sale history and creates another active listing lifecycle.
- Sold Cards ledger actions render inside the AG Grid actions column. Buttons must wrap inside the cell and remain compact enough for pagination-sized rows.
- The shared sale modal must collect sold date, sold price, bought price, and net income. It also previews marketplace fee amount/percent from sold price minus net income/settlement. Do not relabel bought price as bought date.

## Sold Cards and Income Rules

- Sold Cards should be treated as completed listing lifecycles, not as a separate card type.
- Restocking should create a new active listing lifecycle and keep the old sale history intact.
- `sold_price_idr` is the gross sale amount before marketplace deductions.
- `bought_at_price_idr` is the acquisition cost.
- `net_income_idr` is manual for now and should not be inferred until marketplace-fee rules are explicitly added.
- The current marketplace fee calculation is a modal-only preview. It treats `net_income_idr` as settlement/payout for v1 and does not persist fee fields.
- Future marketplace fee analysis should use `sold_price_idr` as the base, then derive fee amount, payout, profit, margin, and ROI without deleting the manually entered net income.
- Existing sold cards must remain editable because sales data can be backfilled after the item was marked sold by sync.
- Sold Cards uses client-side AG Grid pagination with 25, 50, and 100 row page sizes. Server-side pagination should wait until sold history grows into the thousands of rows.
- Sold Cards rows are `Complete` only when sold date, sold price, bought price, and net income are all present. Otherwise, they show `Missing sale data`.

## Opportunities and Inventory Conversion Rules

- Add Opportunity requires card name, rarity, language, source, source link, and observed price.
- Opportunity rows link to `/opportunities/<slug>` using the same SPA routing style as card details.
- Convert Opportunity requires a bought price. The modal can default it from the opportunity price, but the user can override it.
- Conversion with no listing URL creates owned inventory only. It should appear on Inventory, not Store Listings, Repricing Queue, or scheduler runs.
- Conversion with both Tokopedia listing URL and listing price creates owned inventory plus an active Store Listing. This writes to SQLite and appends a scheduler-compatible product to `config/products.json`.
- Do not allow converting an already converted opportunity or adding a duplicate active listing URL.
- Keep converted opportunities visible with a converted status so buying decisions remain auditable.

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
- Check Dashboard, Store Listings, Inventory, Opportunities, Repricing Queue, Sold Cards, Reports, and Card Detail.
- On Dashboard, confirm Live Store Signals, Active Cards preview, Repricing Queue preview, compact `Rp x.xM` KPI values, and inline SVG menu icons.
- On Reports, confirm Source Health renders there and not on Dashboard.
- Confirm AG Grid sorting/filtering/pagination work on Store Listings, Inventory, Opportunities, Source Evidence, Sold Cards, and Repricing Queue.
- On Card Detail Source Evidence, confirm SnkrDunk rows show converted IDR with raw JPY underneath, source badges use distinct retro colors, and the Match column shows score plus Comparable/Excluded status.
- Add an opportunity, open its detail page, convert it to inventory only, and confirm it appears on Inventory without appearing on Store Listings.
- Convert another opportunity with Tokopedia URL and listing price, then confirm it appears on Inventory, Store Listings, and Repricing Queue.
- Confirm Repricing Queue summary counts, action filters, and sort controls update the grid correctly.
- Confirm Dashboard active count, Store Listings rows, Inventory active listing rows, and Repricing Queue rows agree for active config products. Active cards without scheduler history should appear in Repricing Queue as Missing market data.
- Mark an active card sold and confirm it disappears from Store Listings/Repricing Queue, appears in Sold Cards, and saves sold price, bought price, sold date, and net income.
- Edit an existing sold card and confirm the same sale fields update in Sold Cards.
- Restore a sold card with Restore Active and confirm it disappears from Sold Cards, returns to Store Listings, and no longer contributes to income totals.
- Restock a sold card with Restock as New and confirm the old sale remains visible while the card returns to Store Listings as a new active lifecycle.
- Trigger scheduler and single-card refresh; buttons should disable/show progress.
- Confirm source failures render as status badges on Reports.
