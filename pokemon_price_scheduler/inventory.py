from __future__ import annotations

import re
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .models import Product, utc_now


DEFAULT_DB_PATH = Path("data/price_history.sqlite3")


@dataclass(frozen=True)
class SaleInput:
    sold_at: str
    sold_price_idr: int
    bought_at_price_idr: int
    net_income_idr: int


def connect(path: Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = ON")
    init_db(conn)
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS cards (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            set_symbol TEXT DEFAULT '',
            card_number TEXT DEFAULT '',
            rarity TEXT DEFAULT '',
            language TEXT DEFAULT '',
            condition TEXT DEFAULT '',
            display_title TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS listings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            card_id TEXT NOT NULL REFERENCES cards(id),
            slug TEXT NOT NULL,
            title TEXT NOT NULL,
            tokopedia_url TEXT DEFAULT '',
            normalized_url TEXT DEFAULT '',
            status TEXT NOT NULL DEFAULT 'active',
            listed_price_idr INTEGER NOT NULL DEFAULT 0,
            current_price_idr INTEGER NOT NULL DEFAULT 0,
            added_at TEXT DEFAULT '',
            sold_at TEXT DEFAULT '',
            lifecycle INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS sales (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            listing_id INTEGER NOT NULL UNIQUE REFERENCES listings(id),
            card_id TEXT NOT NULL REFERENCES cards(id),
            slug TEXT NOT NULL,
            bought_at TEXT,
            bought_at_price_idr INTEGER,
            sold_at TEXT,
            sold_price_idr INTEGER,
            net_income_idr INTEGER,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_listings_slug_status ON listings(slug, status);
        CREATE INDEX IF NOT EXISTS idx_listings_normalized_status ON listings(normalized_url, status);
        CREATE INDEX IF NOT EXISTS idx_sales_sold_at ON sales(sold_at);
        """
    )
    _ensure_column(conn, "sales", "bought_at_price_idr", "INTEGER")
    _ensure_column(conn, "sales", "sold_price_idr", "INTEGER")
    conn.commit()


def sync_products(products: list[Product], path: Path = DEFAULT_DB_PATH) -> None:
    with closing(connect(path)) as conn:
        now = utc_now().isoformat()
        for product in products:
            _upsert_card(conn, product, now)
            if product.status == "sold":
                listing_id = _ensure_sold_listing(conn, product, now)
                _ensure_sale(conn, listing_id, product, now)
            else:
                _ensure_active_listing(conn, product, now)
        conn.commit()


def mark_product_sold(product: Product, sale: SaleInput, path: Path = DEFAULT_DB_PATH) -> None:
    with closing(connect(path)) as conn:
        now = utc_now().isoformat()
        _upsert_card(conn, product, now)
        listing_id = _find_active_listing_id(conn, product)
        if listing_id is None:
            listing_id = _create_listing(conn, product, "active", now)
        conn.execute(
            """
            UPDATE listings
            SET status = 'sold', sold_at = ?, current_price_idr = ?, updated_at = ?
            WHERE id = ?
            """,
            (sale.sold_at, product.own_price_idr, now, listing_id),
        )
        _upsert_sale(conn, listing_id, product, sale, now)
        conn.commit()


def update_sale_details(product: Product, sale: SaleInput, path: Path = DEFAULT_DB_PATH) -> None:
    with closing(connect(path)) as conn:
        now = utc_now().isoformat()
        _upsert_card(conn, product, now)
        listing_id = _find_sold_listing_id(conn, product)
        if listing_id is None:
            listing_id = _ensure_sold_listing(conn, product, now)
        conn.execute(
            """
            UPDATE listings
            SET status = 'sold', sold_at = ?, current_price_idr = ?, updated_at = ?
            WHERE id = ?
            """,
            (sale.sold_at, product.own_price_idr, now, listing_id),
        )
        _upsert_sale(conn, listing_id, product, sale, now)
        conn.commit()


def create_restock_listing(product: Product, path: Path = DEFAULT_DB_PATH) -> None:
    with closing(connect(path)) as conn:
        now = utc_now().isoformat()
        _upsert_card(conn, product, now)
        if _find_active_listing_id(conn, product) is None:
            _create_listing(conn, product, "active", now)
        conn.commit()


def sold_card_rows(path: Path = DEFAULT_DB_PATH) -> list[dict[str, Any]]:
    with closing(connect(path)) as conn:
        rows = conn.execute(
            """
            SELECT l.slug, l.title, l.current_price_idr, l.sold_at,
                   c.language, s.bought_at_price_idr, s.sold_price_idr, s.net_income_idr
            FROM listings l
            LEFT JOIN cards c ON c.id = l.card_id
            LEFT JOIN sales s ON s.listing_id = l.id
            WHERE l.status = 'sold'
            ORDER BY COALESCE(s.sold_at, l.sold_at) DESC, l.id DESC
            """
        ).fetchall()
    return [
        {
            "slug": row[0],
            "title": row[1],
            "own_price_idr": int(row[2] or 0),
            "sold_at": row[3] or "",
            "language": row[4] or "-",
            "bought_at_price_idr": int(row[5]) if row[5] is not None else None,
            "sold_price_idr": int(row[6]) if row[6] is not None else None,
            "net_income_idr": int(row[7]) if row[7] is not None else None,
        }
        for row in rows
    ]


def income_summary(path: Path = DEFAULT_DB_PATH) -> dict[str, Any]:
    with closing(connect(path)) as conn:
        total = conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(net_income_idr), 0) FROM sales WHERE net_income_idr IS NOT NULL"
        ).fetchone()
        monthly = conn.execute(
            """
            SELECT substr(sold_at, 1, 7) AS period, COUNT(*), COALESCE(SUM(net_income_idr), 0)
            FROM sales
            WHERE sold_at IS NOT NULL AND sold_at != '' AND net_income_idr IS NOT NULL
            GROUP BY period
            ORDER BY period DESC
            LIMIT 6
            """
        ).fetchall()
        weekly = conn.execute(
            """
            SELECT strftime('%Y-W%W', substr(sold_at, 1, 10)) AS period, COUNT(*), COALESCE(SUM(net_income_idr), 0)
            FROM sales
            WHERE sold_at IS NOT NULL AND sold_at != '' AND net_income_idr IS NOT NULL
            GROUP BY period
            ORDER BY period DESC
            LIMIT 6
            """
        ).fetchall()
    return {
        "sold_count": int(total[0] or 0),
        "net_income_idr": int(total[1] or 0),
        "monthly": [{"period": r[0], "count": int(r[1]), "net_income_idr": int(r[2])} for r in monthly],
        "weekly": [{"period": r[0], "count": int(r[1]), "net_income_idr": int(r[2])} for r in weekly],
    }


def _card_id(product: Product) -> str:
    return product.slug


def _normalized_url(url: str) -> str:
    parsed = urlparse(url)
    path = parsed.path.rstrip("/")
    if not path:
        return ""
    host = parsed.netloc.lower()
    return f"{host}{path}" if host else path


def _upsert_card(conn: sqlite3.Connection, product: Product, now: str) -> None:
    identity = product.card_identity
    conn.execute(
        """
        INSERT INTO cards(
            id, name, set_symbol, card_number, rarity, language, condition,
            display_title, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            name = excluded.name,
            set_symbol = excluded.set_symbol,
            card_number = excluded.card_number,
            rarity = excluded.rarity,
            language = excluded.language,
            condition = excluded.condition,
            display_title = excluded.display_title,
            updated_at = excluded.updated_at
        """,
        (
            _card_id(product),
            identity.name or product.title,
            identity.set_symbol,
            identity.card_number,
            identity.rarity,
            identity.language,
            identity.condition,
            product.title,
            now,
            now,
        ),
    )


def _find_active_listing_id(conn: sqlite3.Connection, product: Product) -> int | None:
    normalized = _normalized_url(product.tokopedia_url)
    if normalized:
        row = conn.execute(
            """
            SELECT id FROM listings
            WHERE normalized_url = ? AND status = 'active'
            ORDER BY id DESC LIMIT 1
            """,
            (normalized,),
        ).fetchone()
        if row:
            return int(row[0])
    row = conn.execute(
        "SELECT id FROM listings WHERE slug = ? AND status = 'active' ORDER BY id DESC LIMIT 1",
        (product.slug,),
    ).fetchone()
    return int(row[0]) if row else None


def _find_sold_listing_id(conn: sqlite3.Connection, product: Product) -> int | None:
    normalized = _normalized_url(product.tokopedia_url)
    if normalized:
        row = conn.execute(
            """
            SELECT id FROM listings
            WHERE normalized_url = ? AND status = 'sold'
            ORDER BY id DESC LIMIT 1
            """,
            (normalized,),
        ).fetchone()
        if row:
            return int(row[0])
    row = conn.execute(
        "SELECT id FROM listings WHERE slug = ? AND status = 'sold' ORDER BY id DESC LIMIT 1",
        (product.slug,),
    ).fetchone()
    return int(row[0]) if row else None


def _ensure_active_listing(conn: sqlite3.Connection, product: Product, now: str) -> int:
    listing_id = _find_active_listing_id(conn, product)
    if listing_id is None:
        return _create_listing(conn, product, "active", now)
    conn.execute(
        """
        UPDATE listings
        SET title = ?, tokopedia_url = ?, normalized_url = ?, current_price_idr = ?,
            added_at = ?, updated_at = ?
        WHERE id = ?
        """,
        (
            product.title,
            product.tokopedia_url,
            _normalized_url(product.tokopedia_url),
            product.own_price_idr,
            product.added_at,
            now,
            listing_id,
        ),
    )
    return listing_id


def _ensure_sold_listing(conn: sqlite3.Connection, product: Product, now: str) -> int:
    normalized = _normalized_url(product.tokopedia_url)
    row = None
    if normalized:
        row = conn.execute(
            """
            SELECT id FROM listings
            WHERE normalized_url = ? AND status = 'sold'
            ORDER BY id DESC LIMIT 1
            """,
            (normalized,),
        ).fetchone()
    if row is None:
        row = conn.execute(
            "SELECT id FROM listings WHERE slug = ? AND status = 'sold' ORDER BY id DESC LIMIT 1",
            (product.slug,),
        ).fetchone()
    if row:
        listing_id = int(row[0])
        conn.execute(
            """
            UPDATE listings
            SET title = ?, current_price_idr = ?, sold_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (product.title, product.own_price_idr, product.sold_at, now, listing_id),
        )
        return listing_id
    return _create_listing(conn, product, "sold", now)


def _create_listing(conn: sqlite3.Connection, product: Product, status: str, now: str) -> int:
    normalized = _normalized_url(product.tokopedia_url)
    lifecycle = 1
    if normalized:
        row = conn.execute(
            "SELECT COALESCE(MAX(lifecycle), 0) + 1 FROM listings WHERE normalized_url = ?",
            (normalized,),
        ).fetchone()
        lifecycle = int(row[0] or 1)
    cursor = conn.execute(
        """
        INSERT INTO listings(
            card_id, slug, title, tokopedia_url, normalized_url, status,
            listed_price_idr, current_price_idr, added_at, sold_at, lifecycle,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            _card_id(product),
            product.slug,
            product.title,
            product.tokopedia_url,
            normalized,
            status,
            product.own_price_idr,
            product.own_price_idr,
            product.added_at,
            product.sold_at,
            lifecycle,
            now,
            now,
        ),
    )
    return int(cursor.lastrowid)


def _ensure_sale(conn: sqlite3.Connection, listing_id: int, product: Product, now: str) -> None:
    conn.execute(
        """
        INSERT INTO sales(listing_id, card_id, slug, bought_at, bought_at_price_idr, sold_at, sold_price_idr, net_income_idr, created_at, updated_at)
        VALUES (?, ?, ?, NULL, NULL, ?, NULL, NULL, ?, ?)
        ON CONFLICT(listing_id) DO UPDATE SET
            sold_at = COALESCE(sales.sold_at, excluded.sold_at),
            updated_at = excluded.updated_at
        """,
        (listing_id, _card_id(product), product.slug, product.sold_at or None, now, now),
    )


def _upsert_sale(conn: sqlite3.Connection, listing_id: int, product: Product, sale: SaleInput, now: str) -> None:
    conn.execute(
        """
        INSERT INTO sales(listing_id, card_id, slug, bought_at_price_idr, sold_at, sold_price_idr, net_income_idr, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(listing_id) DO UPDATE SET
            bought_at_price_idr = excluded.bought_at_price_idr,
            sold_at = excluded.sold_at,
            sold_price_idr = excluded.sold_price_idr,
            net_income_idr = excluded.net_income_idr,
            updated_at = excluded.updated_at
        """,
        (
            listing_id,
            _card_id(product),
            product.slug,
            sale.bought_at_price_idr,
            sale.sold_at,
            sale.sold_price_idr,
            sale.net_income_idr,
            now,
            now,
        ),
    )


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, column_type: str) -> None:
    existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_type}")


def parse_idr(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    text = str(value or "").strip()
    if not text:
        return None
    digits = re.sub(r"\D", "", text)
    if not digits:
        return None
    return int(digits)
