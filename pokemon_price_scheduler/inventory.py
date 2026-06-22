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


@dataclass(frozen=True)
class OpportunityInput:
    card_name: str
    card_rarity: str
    card_language: str
    source: str
    link: str
    price_idr: int


@dataclass(frozen=True)
class ConvertOpportunityInput:
    bought_at_price_idr: int
    tokopedia_url: str = ""
    listing_price_idr: int | None = None


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
        CREATE TABLE IF NOT EXISTS opportunities (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            slug TEXT NOT NULL UNIQUE,
            card_name TEXT NOT NULL,
            card_rarity TEXT NOT NULL,
            card_language TEXT NOT NULL,
            source TEXT NOT NULL,
            link TEXT NOT NULL,
            price_idr INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'open',
            converted_inventory_id INTEGER,
            converted_listing_id INTEGER,
            created_at TEXT NOT NULL,
            converted_at TEXT DEFAULT '',
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS inventory_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            card_id TEXT NOT NULL REFERENCES cards(id),
            opportunity_id INTEGER REFERENCES opportunities(id),
            listing_id INTEGER REFERENCES listings(id),
            slug TEXT NOT NULL,
            title TEXT NOT NULL,
            card_name TEXT NOT NULL,
            card_rarity TEXT NOT NULL,
            card_language TEXT NOT NULL,
            bought_at_price_idr INTEGER NOT NULL,
            quantity INTEGER NOT NULL DEFAULT 1,
            status TEXT NOT NULL DEFAULT 'owned',
            source TEXT DEFAULT '',
            link TEXT DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_listings_slug_status ON listings(slug, status);
        CREATE INDEX IF NOT EXISTS idx_listings_normalized_status ON listings(normalized_url, status);
        CREATE INDEX IF NOT EXISTS idx_sales_sold_at ON sales(sold_at);
        CREATE INDEX IF NOT EXISTS idx_opportunities_status ON opportunities(status);
        CREATE INDEX IF NOT EXISTS idx_inventory_items_slug ON inventory_items(slug);
        """
    )
    _ensure_column(conn, "sales", "bought_at_price_idr", "INTEGER")
    _ensure_column(conn, "sales", "sold_price_idr", "INTEGER")
    conn.commit()


def create_opportunity(data: OpportunityInput, path: Path = DEFAULT_DB_PATH) -> dict[str, Any]:
    with closing(connect(path)) as conn:
        now = utc_now().isoformat()
        base_slug = slugify(" ".join([data.card_name, data.card_rarity, data.card_language]))
        slug = _unique_opportunity_slug(conn, base_slug)
        cursor = conn.execute(
            """
            INSERT INTO opportunities(
                slug, card_name, card_rarity, card_language, source, link,
                price_idr, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'open', ?, ?)
            """,
            (
                slug,
                data.card_name,
                data.card_rarity,
                data.card_language,
                data.source,
                data.link,
                data.price_idr,
                now,
                now,
            ),
        )
        conn.commit()
        opportunity_id = int(cursor.lastrowid)
    return get_opportunity(slug, path) or {"id": opportunity_id, "slug": slug}


def list_opportunities(path: Path = DEFAULT_DB_PATH) -> list[dict[str, Any]]:
    with closing(connect(path)) as conn:
        rows = conn.execute(
            """
            SELECT id, slug, card_name, card_rarity, card_language, source, link,
                   price_idr, status, converted_inventory_id, converted_listing_id,
                   created_at, converted_at
            FROM opportunities
            ORDER BY CASE status WHEN 'open' THEN 0 ELSE 1 END, id DESC
            """
        ).fetchall()
    return [_opportunity_row(row) for row in rows]


def get_opportunity(slug: str, path: Path = DEFAULT_DB_PATH) -> dict[str, Any] | None:
    with closing(connect(path)) as conn:
        row = conn.execute(
            """
            SELECT id, slug, card_name, card_rarity, card_language, source, link,
                   price_idr, status, converted_inventory_id, converted_listing_id,
                   created_at, converted_at
            FROM opportunities
            WHERE slug = ?
            """,
            (slug,),
        ).fetchone()
    return _opportunity_row(row) if row else None


def convert_opportunity(
    slug: str,
    data: ConvertOpportunityInput,
    *,
    product: Product | None = None,
    path: Path = DEFAULT_DB_PATH,
) -> dict[str, Any] | None:
    with closing(connect(path)) as conn:
        now = utc_now().isoformat()
        row = conn.execute(
            """
            SELECT id, slug, card_name, card_rarity, card_language, source, link,
                   price_idr, status, converted_inventory_id, converted_listing_id,
                   created_at, converted_at
            FROM opportunities
            WHERE slug = ?
            """,
            (slug,),
        ).fetchone()
        if row is None:
            return None
        opportunity = _opportunity_row(row)
        product_for_card = product or _product_from_opportunity(opportunity, data)
        _upsert_card(conn, product_for_card, now)
        listing_id = None
        if product is not None and product.tokopedia_url:
            listing_id = _ensure_active_listing(conn, product, now)
        inventory_id = _create_inventory_item(conn, opportunity, product_for_card, data, listing_id, now)
        conn.execute(
            """
            UPDATE opportunities
            SET status = 'converted',
                converted_inventory_id = ?,
                converted_listing_id = ?,
                converted_at = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (inventory_id, listing_id, now, now, opportunity["id"]),
        )
        conn.commit()
    return get_opportunity(slug, path)


def inventory_rows(path: Path = DEFAULT_DB_PATH) -> list[dict[str, Any]]:
    with closing(connect(path)) as conn:
        owned_rows = conn.execute(
            """
            SELECT slug, title, card_name, card_rarity, card_language,
                   bought_at_price_idr, quantity, status, source, link
            FROM inventory_items
            ORDER BY id DESC
            """
        ).fetchall()
        listing_rows = conn.execute(
            """
            SELECT l.slug, l.title, c.name, c.rarity, c.language,
                   l.current_price_idr, l.status
            FROM listings l
            LEFT JOIN cards c ON c.id = l.card_id
            ORDER BY l.id DESC
            """
        ).fetchall()
    rows = [
        {
            "slug": row[0],
            "title": row[1],
            "card_name": row[2],
            "card_rarity": row[3],
            "card_language": row[4],
            "bought_at_price_idr": int(row[5] or 0),
            "quantity": int(row[6] or 0),
            "status": row[7],
            "source": row[8],
            "link": row[9],
            "type": "owned",
        }
        for row in owned_rows
    ]
    rows.extend(
        {
            "slug": row[0],
            "title": row[1],
            "card_name": row[2] or row[1],
            "card_rarity": row[3] or "-",
            "card_language": row[4] or "-",
            "bought_at_price_idr": int(row[5] or 0),
            "quantity": 1 if row[6] != "sold" else 0,
            "status": row[6],
            "source": "Tokopedia listing",
            "link": "",
            "type": "listing",
        }
        for row in listing_rows
    )
    return rows


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
        _delete_stale_active_listings(conn, products)
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


def restore_active_listing(product: Product, path: Path = DEFAULT_DB_PATH) -> bool:
    with closing(connect(path)) as conn:
        now = utc_now().isoformat()
        _upsert_card(conn, product, now)
        listing_id = _find_sold_listing_id(conn, product)
        if listing_id is None:
            return False
        active_listing_id = _find_active_listing_id(conn, product)
        conn.execute("DELETE FROM sales WHERE listing_id = ?", (listing_id,))
        if active_listing_id is not None:
            conn.execute("DELETE FROM listings WHERE id = ?", (listing_id,))
            conn.commit()
            return True
        conn.execute(
            """
            UPDATE listings
            SET status = 'active',
                sold_at = '',
                title = ?,
                tokopedia_url = ?,
                normalized_url = ?,
                current_price_idr = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                product.title,
                product.tokopedia_url,
                _normalized_url(product.tokopedia_url),
                product.own_price_idr,
                now,
                listing_id,
            ),
        )
        conn.commit()
        return True


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


def _delete_stale_active_listings(conn: sqlite3.Connection, products: list[Product]) -> None:
    active_slugs = {product.slug for product in products if product.status != "sold"}
    active_urls = {
        normalized
        for product in products
        if product.status != "sold"
        for normalized in [_normalized_url(product.tokopedia_url)]
        if normalized
    }
    rows = conn.execute(
        "SELECT id, slug, normalized_url FROM listings WHERE status = 'active'"
    ).fetchall()
    stale_ids = [
        int(row[0])
        for row in rows
        if str(row[1]) not in active_slugs and (not row[2] or str(row[2]) not in active_urls)
    ]
    if not stale_ids:
        return
    conn.executemany("DELETE FROM listings WHERE id = ?", [(listing_id,) for listing_id in stale_ids])


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


def slugify(value: str) -> str:
    tokens = [token for token in re.sub(r"[^a-z0-9]+", "-", value.lower()).split("-") if token]
    return "-".join(tokens)[:90] or "opportunity"


def _unique_opportunity_slug(conn: sqlite3.Connection, base_slug: str) -> str:
    slug = base_slug or "opportunity"
    index = 2
    while conn.execute("SELECT 1 FROM opportunities WHERE slug = ?", (slug,)).fetchone():
        suffix = f"-{index}"
        slug = f"{base_slug[:90 - len(suffix)]}{suffix}"
        index += 1
    return slug


def _opportunity_row(row: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "id": int(row[0]),
        "slug": row[1],
        "card_name": row[2],
        "card_rarity": row[3],
        "card_language": row[4],
        "source": row[5],
        "link": row[6],
        "price_idr": int(row[7] or 0),
        "status": row[8],
        "converted_inventory_id": int(row[9]) if row[9] is not None else None,
        "converted_listing_id": int(row[10]) if row[10] is not None else None,
        "created_at": row[11] or "",
        "converted_at": row[12] or "",
        "title": " ".join(part for part in (row[2], row[3], row[4]) if part),
    }


def _product_from_opportunity(opportunity: dict[str, Any], data: ConvertOpportunityInput) -> Product:
    title = opportunity["title"]
    return Product(
        title=title,
        own_price_idr=data.listing_price_idr or data.bought_at_price_idr,
        tokopedia_url=data.tokopedia_url,
        search_terms=[title],
        sources=[],
        status="active" if data.tokopedia_url else "owned",
        added_at=utc_now().isoformat(),
    )


def _create_inventory_item(
    conn: sqlite3.Connection,
    opportunity: dict[str, Any],
    product: Product,
    data: ConvertOpportunityInput,
    listing_id: int | None,
    now: str,
) -> int:
    cursor = conn.execute(
        """
        INSERT INTO inventory_items(
            card_id, opportunity_id, listing_id, slug, title, card_name,
            card_rarity, card_language, bought_at_price_idr, quantity, status,
            source, link, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            _card_id(product),
            opportunity["id"],
            listing_id,
            product.slug,
            product.title,
            opportunity["card_name"],
            opportunity["card_rarity"],
            opportunity["card_language"],
            data.bought_at_price_idr,
            1,
            "listed" if listing_id is not None else "owned",
            opportunity["source"],
            opportunity["link"],
            now,
            now,
        ),
    )
    return int(cursor.lastrowid)
