# Inventory and Sales Model

This document captures the current direction for sold-card and income tracking in the Pokemon Price Tracker.

## Current Direction

The app is moving from a simple `status = sold` archive toward a proper inventory model:

- `cards` represent parsed card identity.
- `listings` represent Tokopedia listing lifecycles.
- `sales` represent completed sales and income data.

`config/products.json` still exists for scheduler compatibility. The live app mirrors listing lifecycle changes into SQLite so income analysis can use durable sale records without breaking the current scheduler.

Inventory sync removes stale active SQLite listing rows that no longer correspond to active config products. Sold lifecycles and owned inventory rows are preserved.

## SQLite Tables

All inventory/sales tables live in `data/price_history.sqlite3` and are initialized by `pokemon_price_scheduler/inventory.py`.

### `cards`

Stable identity record derived from product title parsing.

Important columns:

- `id`: current card id, using the parsed product slug.
- `name`
- `set_symbol`
- `card_number`
- `rarity`
- `language`
- `condition`
- `display_title`
- `created_at`
- `updated_at`

### `listings`

One Tokopedia listing lifecycle.

Important columns:

- `id`
- `card_id`
- `slug`
- `title`
- `tokopedia_url`
- `normalized_url`
- `status`: `active` or `sold`
- `listed_price_idr`
- `current_price_idr`
- `added_at`
- `sold_at`
- `lifecycle`
- `created_at`
- `updated_at`

Restocking should create a new active listing lifecycle, not overwrite the old sale.

### `sales`

One completed sale record linked to a sold listing.

Important columns:

- `listing_id`
- `card_id`
- `slug`
- `sold_at`
- `sold_price_idr`: gross sale price before marketplace fee.
- `bought_at_price_idr`: acquisition cost.
- `net_income_idr`: manually entered net income.
- `created_at`
- `updated_at`

The legacy `bought_at` column may exist in SQLite for backward compatibility, but the current app does not use it. The correct field is `bought_at_price_idr`.

## Manual Workflows

### Mark Active Card Sold

Use `POST /api/cards/<slug>/mark-sold`.

Required JSON:

```json
{
  "sold_at": "2026-06-07",
  "sold_price_idr": 2500000,
  "bought_at_price_idr": 1500000,
  "net_income_idr": 2300000
}
```

Behavior:

- Updates the config product to `status = sold`.
- Sets config `sold_at`.
- Marks the active SQLite listing as sold.
- Creates or updates the linked `sales` row.
- Removes the card from active cards and repricing queue.
- Shows the card on Sold Cards.

### Edit Existing Sold Card

Use `POST /api/cards/<slug>/sale-details`.

Required JSON is the same as Mark Sold.

Behavior:

- Keeps the card sold.
- Updates `sold_at` in config and SQLite.
- Updates `sold_price_idr`, `bought_at_price_idr`, and `net_income_idr`.
- Allows backfilling existing sold cards that were detected by store sync before income fields existed.

### Restore Active

Use `PUT /api/cards/<slug>/restore-active`.

Behavior:

- Treats the sold state as a mistaken snapshot or correction.
- Updates the config product back to `active`.
- Clears config `sold_at`.
- Moves the existing sold SQLite listing back to `active`.
- Clears listing `sold_at`.
- Deletes the linked `sales` row so Sold Cards and income totals no longer count it.
- Does not create a new listing lifecycle.
- If config already says the product is active but SQLite still has a sold listing for the same slug/URL, Restore Active cleans that stale sold snapshot and linked sale row without creating another active listing.

### Restock as New

Use `PUT /api/cards/<slug>/revert-sold`.

Behavior:

- Updates the config product back to `active`.
- Creates a new active listing lifecycle in SQLite.
- Preserves the previous sold listing and sale record.

## UI Rules

Card detail:

- Active cards show `Mark Sold`.
- Sold cards show `Edit Sale`.

Sold Cards page:

- Starts with `Sales Summary`.
- Shows a searchable, filterable AG Grid sales ledger with listing price, sold price, bought price, sold date, net income, and data quality.
- Provides `Edit Sale`, `Restore Active`, and `Restock as New` from the ledger actions column.
- Uses client-side pagination with 25, 50, and 100 row page sizes.
- Marks rows as `Complete` only when sold date, sold price, bought price, and net income are all present; otherwise rows show `Missing sale data`.

The sale modal must collect:

- Sold date
- Sold price
- Bought price
- Net income

The modal also previews marketplace fee:

- `marketplace_fee_idr = sold_price_idr - net_income_idr`
- `marketplace_fee_percent = marketplace_fee_idr / sold_price_idr * 100`

For this v1 preview, `net_income_idr` is treated as the marketplace settlement/payout value. The fee amount and percent are not stored in SQLite.

Do not rename bought price to bought date. Bought date is not part of the current workflow.

## Income Analysis Notes

Current income analytics are intentionally simple:

- Net income is manual.
- Monthly/weekly summaries use `sales.sold_at`.
- Totals use `sales.net_income_idr`.
- Marketplace fee amount/percent is a sale-modal preview only and is recalculated from the current inputs.

Future marketplace-fee analysis should build on the captured gross sold price:

- `marketplace_fee_percent`
- `marketplace_fee_idr = sold_price_idr * marketplace_fee_percent`
- payout/net estimate
- profit = net income or payout minus bought price
- margin percent
- ROI percent

When adding calculated fields, keep manual `net_income_idr` available as an override or actual payout field. Do not silently replace user-entered net income.

## Compatibility Notes

- The scheduler still reads products from `config/products.json`.
- Dashboard, Store Listings, and Repricing Queue continue to filter active listings from config.
- Sold Cards and sale summaries read from SQLite after syncing config products into inventory tables.
- Inventory active listing rows should match active config products after sync. Extra active SQLite rows are stale and should be pruned.
- Opportunities can create inventory-only rows or active listing rows. See `OPPORTUNITIES_INVENTORY.md` for the buy-list conversion workflow.
- Tests should cover both config state and SQLite inventory state after each lifecycle mutation.

## Regression Checklist

- Mark Sold requires sold date, sold price, bought price, and net income.
- Mark Sold removes the item from Store Listings and Repricing Queue.
- Mark Sold creates a `sales` row.
- Edit Sale updates existing sold cards without creating duplicate sales.
- Restore Active removes a mistaken sold snapshot, deletes its sale row, and returns the same listing to active.
- Restock as New creates a new active listing lifecycle while preserving the old sale.
- Existing scheduler runs and price history snapshots still work for active listings.
