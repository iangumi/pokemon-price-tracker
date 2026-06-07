"""SQLite persistence — infrastructure concern."""

from __future__ import annotations

import sqlite3
import threading
import json
from pathlib import Path

from ..domain.models import ProductAnalysis, utc_now

DB_PATH = Path("data/price_history.sqlite3")

_local = threading.local()


def connect(path: Path | None = None) -> sqlite3.Connection:
    """Return a thread-local connection, creating it if needed."""
    if path is None:
        path = DB_PATH
    if not hasattr(_local, "conn") or _local.conn is None:
        path.parent.mkdir(parents=True, exist_ok=True)
        _local.conn = sqlite3.connect(path, check_same_thread=False)
        _local.conn.execute("PRAGMA foreign_keys = ON")
        init_db(_local.conn)
    return _local.conn


def close_connection() -> None:
    """Close the current thread's cached SQLite connection, if any."""
    conn = getattr(_local, "conn", None)
    if conn is not None:
        conn.close()
        _local.conn = None


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS product_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER NOT NULL REFERENCES runs(id),
            slug TEXT NOT NULL,
            title TEXT NOT NULL,
            language TEXT NOT NULL,
            own_price_idr INTEGER NOT NULL,
            market_min_idr INTEGER,
            market_median_idr INTEGER,
            global_average_idr INTEGER,
            price_delta_percent REAL,
            alert_level TEXT DEFAULT 'none',
            underpriced_by_idr INTEGER,
            underpriced_by_percent REAL,
            recommendation TEXT NOT NULL,
            ai_summary TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS observations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_result_id INTEGER NOT NULL REFERENCES product_results(id),
            source_name TEXT NOT NULL,
            source_kind TEXT NOT NULL,
            url TEXT NOT NULL,
            title TEXT,
            price_idr INTEGER NOT NULL,
            raw_price TEXT,
            is_legit INTEGER NOT NULL,
            relevance_score REAL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS price_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER REFERENCES runs(id),
            product_result_id INTEGER REFERENCES product_results(id),
            card_id TEXT NOT NULL,
            tokopedia_price INTEGER NOT NULL,
            market_avg_price INTEGER,
            delta_percent REAL,
            alert_status TEXT DEFAULT 'none',
            source_summary TEXT DEFAULT '',
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_product_results_slug ON product_results(slug);
        CREATE INDEX IF NOT EXISTS idx_price_history_card_created ON price_history(card_id, created_at);
        """
    )
    _ALLOWED_MIGRATIONS = {
        ("product_results", "global_average_idr", "INTEGER"),
        ("product_results", "price_delta_percent", "REAL"),
        ("product_results", "alert_level", "TEXT DEFAULT 'none'"),
        ("product_results", "ai_summary", "TEXT DEFAULT ''"),
        ("product_results", "alert_label", "TEXT DEFAULT ''"),
        ("observations", "relevance_score", "REAL DEFAULT 0"),
    }
    for table, column, column_type in _ALLOWED_MIGRATIONS:
        existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_type}")
    _ensure_price_history_minute_index(conn)
    conn.commit()


def save_run(analyses: list[ProductAnalysis]) -> int:
    from ..domain.models import alert_label
    conn = connect()
    run_at = analyses[0].run_at.isoformat() if analyses else ""
    cursor = conn.execute("INSERT INTO runs(run_at) VALUES (?)", (run_at,))
    run_id = int(cursor.lastrowid)
    for analysis in analyses:
        result_cursor = conn.execute(
            """
            INSERT INTO product_results(
                run_id, slug, title, language, own_price_idr, market_min_idr,
                market_median_idr, global_average_idr, price_delta_percent, alert_level,
                underpriced_by_idr, underpriced_by_percent, recommendation, ai_summary,
                alert_label
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                analysis.product.slug,
                analysis.product.title,
                analysis.product.language,
                analysis.product.own_price_idr,
                analysis.market_min_idr,
                analysis.market_median_idr,
                analysis.global_average_idr,
                analysis.price_delta_percent,
                analysis.alert_level,
                analysis.underpriced_by_idr,
                analysis.underpriced_by_percent,
                analysis.recommendation,
                analysis.ai_summary,
                alert_label(analysis.alert_level),
            ),
        )
        result_id = int(result_cursor.lastrowid)
        for source_result in analysis.source_results:
            for obs in source_result.observations:
                conn.execute(
                    """
                    INSERT INTO observations(
                        product_result_id, source_name, source_kind, url, title,
                        price_idr, raw_price, is_legit, relevance_score
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        result_id,
                        obs.source_name,
                        obs.source_kind,
                        obs.url,
                        obs.title,
                        obs.price_idr,
                        obs.raw_price,
                        int(obs.is_legit),
                        obs.relevance_score,
                    ),
                )
        _upsert_price_snapshot(
            conn,
            card_id=analysis.product.slug,
            tokopedia_price=analysis.product.own_price_idr,
            market_avg_price=analysis.global_average_idr,
            delta_percent=analysis.price_delta_percent,
            alert_status=analysis.alert_level,
            source_summary=_source_summary(analysis),
            created_at=run_at,
            run_id=run_id,
            product_result_id=result_id,
        )
    conn.commit()
    return run_id


def record_price_snapshot(
    *,
    card_id: str,
    tokopedia_price: int,
    market_avg_price: int | None = None,
    delta_percent: float | None = None,
    alert_status: str = "none",
    source_summary: str = "",
    run_id: int | None = None,
    product_result_id: int | None = None,
    created_at: str | None = None,
) -> None:
    conn = connect()
    _upsert_price_snapshot(
        conn,
        card_id=card_id,
        tokopedia_price=tokopedia_price,
        market_avg_price=market_avg_price,
        delta_percent=delta_percent,
        alert_status=alert_status,
        source_summary=source_summary,
        created_at=created_at or utc_now().isoformat(),
        run_id=run_id,
        product_result_id=product_result_id,
    )
    conn.commit()


def _upsert_price_snapshot(
    conn: sqlite3.Connection,
    *,
    card_id: str,
    tokopedia_price: int,
    market_avg_price: int | None = None,
    delta_percent: float | None = None,
    alert_status: str = "none",
    source_summary: str = "",
    created_at: str,
    run_id: int | None = None,
    product_result_id: int | None = None,
) -> None:
    values = (
        run_id,
        product_result_id,
        tokopedia_price,
        market_avg_price,
        delta_percent,
        alert_status,
        source_summary,
        created_at,
        card_id,
        created_at,
    )
    cursor = conn.execute(
        """
        UPDATE price_history
        SET run_id = ?,
            product_result_id = ?,
            tokopedia_price = ?,
            market_avg_price = ?,
            delta_percent = ?,
            alert_status = ?,
            source_summary = ?,
            created_at = ?
        WHERE card_id = ?
          AND substr(created_at, 1, 16) = substr(?, 1, 16)
        """,
        values,
    )
    if cursor.rowcount:
        return
    conn.execute(
        """
        INSERT INTO price_history(
            run_id, product_result_id, card_id, tokopedia_price, market_avg_price,
            delta_percent, alert_status, source_summary, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_id,
            product_result_id,
            card_id,
            tokopedia_price,
            market_avg_price,
            delta_percent,
            alert_status,
            source_summary,
            created_at,
        ),
    )


def _ensure_price_history_minute_index(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        DELETE FROM price_history
        WHERE id NOT IN (
            SELECT MAX(id)
            FROM price_history
            GROUP BY card_id, substr(created_at, 1, 16)
        )
        """
    )
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_price_history_card_minute
        ON price_history(card_id, substr(created_at, 1, 16))
        """
    )


def _source_summary(analysis: ProductAnalysis) -> str:
    sources = []
    for result in analysis.source_results:
        sources.append(
            {
                "source": result.source.name,
                "kind": result.source.kind,
                "observations": len(result.observations),
                "warnings": result.warnings,
            }
        )
    return json.dumps(sources, ensure_ascii=False, sort_keys=True)


def get_observations_for_slug(slug: str) -> list[dict]:
    """Return the most recent observations for a slug from the DB."""
    conn = connect()
    rows = conn.execute(
        """
        SELECT o.source_name, o.source_kind, o.url, o.title, o.price_idr, o.is_legit
        FROM observations o
        JOIN product_results pr ON pr.id = o.product_result_id
        WHERE pr.slug = ?
        AND pr.id = (SELECT MAX(id) FROM product_results WHERE slug = ?)
        ORDER BY o.id
        """,
        (slug, slug),
    ).fetchall()
    return [
        {
            "source_name": row[0],
            "source_kind": row[1],
            "url": row[2],
            "title": row[3],
            "price_idr": int(row[4]),
            "is_legit": bool(row[5]),
        }
        for row in rows
    ]


def history_for_slug(slug: str) -> list[tuple[str, int, int | None]]:
    conn = connect()
    rows = conn.execute(
        """
        SELECT runs.run_at, product_results.own_price_idr, product_results.global_average_idr
        FROM product_results
        JOIN runs ON runs.id = product_results.run_id
        WHERE product_results.slug = ?
        ORDER BY runs.run_at
        """,
        (slug,),
    ).fetchall()
    return [(str(row[0]), int(row[1]), row[2] if row[2] is None else int(row[2])) for row in rows]


def price_history_for_slug(slug: str, limit: int = 30) -> list[dict]:
    conn = connect()
    rows = conn.execute(
        """
        SELECT card_id, tokopedia_price, market_avg_price, delta_percent,
               alert_status, source_summary, created_at
        FROM price_history
        WHERE card_id = ?
        ORDER BY created_at DESC, id DESC
        LIMIT ?
        """,
        (slug, limit),
    ).fetchall()
    return [
        {
            "card_id": str(row[0]),
            "tokopedia_price": int(row[1]),
            "market_avg_price": int(row[2]) if row[2] is not None else None,
            "delta_percent": float(row[3]) if row[3] is not None else None,
            "alert_status": str(row[4] or "none"),
            "source_summary": str(row[5] or ""),
            "created_at": str(row[6]),
        }
        for row in rows
    ]


def price_trend_for_slug(slug: str, days: int) -> float | None:
    conn = connect()
    rows = conn.execute(
        """
        SELECT market_avg_price, created_at
        FROM price_history
        WHERE card_id = ?
        ORDER BY created_at DESC, id DESC
        """,
        (slug,),
    ).fetchall()
    values = [(int(row[0]), str(row[1])) for row in rows if row[0] is not None]
    if len(values) < 2:
        return None
    latest_price, latest_at = values[0]
    cutoff = _iso_timestamp_minus_days(latest_at, days)
    baseline = values[-1][0]
    for price, created_at in values:
        if created_at <= cutoff:
            baseline = price
            break
    if baseline <= 0:
        return None
    return round(((latest_price - baseline) / baseline) * 100, 1)


def suggested_prices(market_avg_price: int | None) -> dict[str, int | None]:
    if market_avg_price is None:
        return {"quick_sale": None, "normal": None, "max_profit": None}
    return {
        "quick_sale": round(market_avg_price * 0.92),
        "normal": round(market_avg_price * 0.98),
        "max_profit": round(market_avg_price * 1.05),
    }


def recommended_action(tokopedia_price: int, market_avg_price: int | None) -> str:
    if market_avg_price is None or market_avg_price <= 0:
        return "Missing market data"
    delta = ((tokopedia_price - market_avg_price) / market_avg_price) * 100
    if delta > 10:
        return "Lower price"
    if delta < -10:
        return "Raise price"
    return "Aligned"


def repricing_queue(active_slugs: set[str] | None = None) -> list[dict]:
    products = get_all_products_with_trend()
    rows = []
    for product in products:
        if active_slugs is not None and product["slug"] not in active_slugs:
            continue
        market_avg = product.get("global_average_idr")
        own_price = int(product.get("own_price_idr") or 0)
        prices = suggested_prices(market_avg)
        rows.append(
            {
                "title": product["title"],
                "slug": product["slug"],
                "tokopedia_price": own_price,
                "market_avg_price": market_avg,
                "delta_percent": product.get("price_delta_percent"),
                "suggested_quick_sale": prices["quick_sale"],
                "suggested_normal": prices["normal"],
                "suggested_max_profit": prices["max_profit"],
                "recommended_action": recommended_action(own_price, market_avg),
            }
        )
    action_order = {"Lower price": 0, "Raise price": 1, "Missing market data": 2, "Aligned": 3}
    return sorted(rows, key=lambda row: (action_order.get(row["recommended_action"], 9), row["title"]))


def _iso_timestamp_minus_days(value: str, days: int) -> str:
    from datetime import datetime, timedelta, timezone

    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return value
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return (parsed - timedelta(days=days)).isoformat()


def get_all_products_with_trend() -> list[dict]:
    """Return all products with their latest price and trend vs previous run."""
    from ..domain.models import alert_label
    conn = connect()
    rows = conn.execute(
        """
        WITH numbered AS (
            SELECT
                slug, title, language, own_price_idr, global_average_idr,
                price_delta_percent, alert_level, alert_label,
                ROW_NUMBER() OVER (PARTITION BY slug ORDER BY id DESC) as rn,
                LAG(own_price_idr) OVER (PARTITION BY slug ORDER BY id DESC) as prev_own,
                LAG(global_average_idr) OVER (PARTITION BY slug ORDER BY id DESC) as prev_global
            FROM product_results
        )
        SELECT slug, title, language, own_price_idr, global_average_idr,
               price_delta_percent, alert_level, alert_label, prev_own, prev_global
        FROM numbered
        WHERE rn = 1
        ORDER BY title
        """,
    ).fetchall()
    products = []
    for row in rows:
        own_price = int(row[3]) if row[3] is not None else 0
        prev_own = int(row[8]) if row[8] is not None else None
        global_avg = int(row[4]) if row[4] is not None else None
        prev_global = int(row[9]) if row[9] is not None else None

        own_trend = None
        if prev_own is not None and prev_own > 0:
            own_trend = ((own_price - prev_own) / prev_own) * 100

        market_trend = None
        if prev_global is not None and prev_global > 0 and global_avg is not None:
            market_trend = ((global_avg - prev_global) / prev_global) * 100

        products.append({
            "slug": str(row[0]),
            "title": str(row[1]),
            "language": str(row[2]) if row[2] else "",
            "own_price_idr": own_price,
            "global_average_idr": global_avg,
            "price_delta_percent": float(row[5]) if row[5] is not None else None,
            "alert_level": str(row[6]) if row[6] else "none",
            "alert_label": alert_label(str(row[6]) or "none"),
            "own_trend_percent": round(own_trend, 1) if own_trend is not None else None,
            "market_trend_percent": round(market_trend, 1) if market_trend is not None else None,
        })
    return products
