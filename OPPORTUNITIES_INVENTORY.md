# Opportunities and Inventory Conversion

This document captures the live buy-list workflow and how opportunities become owned inventory or active Store Listings.

## Purpose

The live `/opportunities` page is a persistent buy list for real cards you are considering buying. It is separate from `reports/opportunities.html`, which remains a static generated market-discovery report from scheduler output.

Use the live page for manual buying decisions, purchase tracking, and conversion into inventory. Use the generated report for discovery signals.

## Live Routes

| Route | Purpose |
|---|---|
| `/opportunities` | Buy-list table with add action and status badges |
| `/opportunities/<slug>` | Opportunity detail page with conversion action |
| `/inventory` | Owned stock view from listing lifecycles and converted opportunities |
| `/cards` | Store Listings: scheduler-visible active Tokopedia listings |

## API Routes

| Route | Method | Purpose |
|---|---|---|
| `/api/opportunities` | GET | Render buy-list AG Grid fragment |
| `/api/opportunities` | POST | Create a new opportunity |
| `/api/opportunities/<slug>` | GET | Render opportunity detail fragment |
| `/api/opportunities/<slug>/convert` | POST | Convert opportunity into inventory and optional active listing |
| `/api/inventory` | GET | Render owned inventory AG Grid fragment |

## Add Opportunity Fields

Required fields:

- `card_name`
- `rarity`
- `language`
- `source`
- `link`
- `price_idr`

The app generates a slug from the card name and stores the opportunity in SQLite. Opportunities stay visible after conversion so purchase decisions remain auditable.

## Conversion Logic

Convert Opportunity requires:

- `bought_at_price_idr`

Optional listing fields:

- `tokopedia_url`
- `listing_price_idr`

Behavior:

- If only bought price is provided, conversion creates an owned `inventory_items` row. The item appears on `/inventory` but does not appear on Store Listings, scheduler runs, or Repricing Queue.
- If Tokopedia URL and listing price are also provided, conversion creates owned inventory plus an active listing lifecycle. It appends a scheduler-compatible product to `config/products.json`, creates a SQLite `listing`, and the item appears on Store Listings and Repricing Queue.
- The app rejects converting an already converted opportunity.
- The app rejects duplicate Tokopedia listing URLs when creating an active listing.
- Converted opportunities are marked `converted` and retain conversion IDs for traceability.

## SQLite Tables

All tables live in `data/price_history.sqlite3` and are initialized by `pokemon_price_scheduler/inventory.py`.

### `opportunities`

Tracks buy-list candidates.

Important columns:

- `id`
- `slug`
- `card_name`
- `rarity`
- `language`
- `source`
- `link`
- `price_idr`
- `status`: currently `open` or `converted`
- `converted_at`
- `converted_card_id`
- `converted_listing_id`
- `converted_inventory_item_id`
- `created_at`
- `updated_at`

### `inventory_items`

Tracks owned stock created from opportunities.

Important columns:

- `id`
- `card_id`
- `opportunity_id`
- `listing_id`
- `slug`
- `title`
- `rarity`
- `language`
- `source`
- `source_link`
- `bought_at_price_idr`
- `status`: `owned`, `listed`, or lifecycle-derived state
- `created_at`
- `updated_at`

## Inventory Count Rules

- Active Store Listings count as listed owned inventory.
- Sold listing lifecycles remain visible for audit and income analysis, but their active stock quantity is zero.
- Inventory-only opportunity conversions count as owned stock but are not scheduler-visible.
- Store Listings should stay focused on active Tokopedia listings. Inventory should answer what the store owns or has owned.

## Compatibility Notes

- `config/products.json` remains the scheduler input for active Store Listings.
- Inventory-only conversions intentionally do not write to `config/products.json`.
- Listing conversions write to both SQLite and `config/products.json` so the scheduler can price the listing.
- `reports/opportunities.html` is not backed by the live `opportunities` table.
- Store Listings keeps the `/cards` route for backward compatibility with earlier app URLs.

## Regression Checklist

- Add an opportunity and confirm it appears on `/opportunities`.
- Open `/opportunities/<slug>` and confirm the detail page uses the retro page layout.
- Convert with bought price only and confirm the item appears on `/inventory` but not `/cards`.
- Convert with bought price, Tokopedia URL, and listing price and confirm it appears on `/inventory`, `/cards`, and Repricing Queue.
- Confirm duplicate listing URLs are rejected during conversion.
- Confirm already converted opportunities cannot be converted again.
- Confirm scheduler runs and price history still operate on active Store Listings only.
