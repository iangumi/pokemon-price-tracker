"""SQLite persistence — infrastructure concern."""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from ..domain.models import ProductAnalysis

DB_PATH = Path("data/price_history.sqlite3")

_local = threading.local()


def connect(path: Path = DB_PATH) -> sqlite3.Connection:
    """Return a thread-local connection, creating it if needed."""
    if not hasattr(_local, "conn") or _local.conn is None:
        path.parent.mkdir(parents=True, exist_ok=True)
        _local.conn = sqlite3.connect(path, check_same_thread=False)
        _local.conn.execute("PRAGMA foreign_keys = ON")
        init_db(_local.conn)
    return _local.conn


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
        CREATE INDEX IF NOT EXISTS idx_product_results_slug ON product_results(slug);
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
    conn.commit()
    return run_id


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