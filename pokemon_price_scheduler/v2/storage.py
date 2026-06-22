from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path

from pokemon_price_scheduler.domain.models import ProductAnalysis, alert_label

from .models import FetchRecord, ObservationDecision, RunEvent


class TraceStore:
    def __init__(self, path: Path = Path("data/price_history.sqlite3")) -> None:
        self.path = path

    def connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path)
        conn.execute("PRAGMA foreign_keys = ON")
        init_db(conn)
        return conn

    def create_run(self, run_at: str, config_snapshot: dict) -> int:
        with closing(self.connect()) as conn:
            cursor = conn.execute(
                "INSERT INTO runs(run_at, status, config_snapshot) VALUES (?, ?, ?)",
                (run_at, "running", json.dumps(config_snapshot, ensure_ascii=False, sort_keys=True)),
            )
            run_id = int(cursor.lastrowid)
            conn.commit()
            return run_id

    def finish_run(self, run_id: int, status: str) -> None:
        with closing(self.connect()) as conn:
            conn.execute("UPDATE runs SET status = ? WHERE id = ?", (status, run_id))
            conn.commit()

    def add_events(self, run_id: int, events: list[RunEvent]) -> None:
        if not events:
            return
        with closing(self.connect()) as conn:
            conn.executemany(
                """
                INSERT INTO run_events(
                    run_id, stage, severity, message, product_id, product_slug,
                    source_name, elapsed_ms, details_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        run_id,
                        event.stage,
                        event.severity,
                        event.message,
                        event.product_id,
                        event.product_slug,
                        event.source_name,
                        event.elapsed_ms,
                        json.dumps(event.details, ensure_ascii=False, sort_keys=True),
                    )
                    for event in events
                ],
            )
            conn.commit()

    def add_fetch_records(self, run_id: int, records: list[FetchRecord]) -> None:
        if not records:
            return
        with closing(self.connect()) as conn:
            conn.executemany(
                """
                INSERT INTO source_fetches(
                    run_id, product_id, product_slug, source_name, source_kind, url,
                    status, started_at, elapsed_ms, response_bytes, content_hash,
                    artifact_path, error, fetch_backend, failure_kind
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        run_id,
                        record.product_id,
                        record.product_slug,
                        record.source_name,
                        record.source_kind,
                        record.url,
                        record.status,
                        record.started_at,
                        record.elapsed_ms,
                        record.response_bytes,
                        record.content_hash,
                        record.artifact_path,
                        record.error,
                        record.fetch_backend,
                        record.failure_kind,
                    )
                    for record in records
                ],
            )
            conn.commit()

    def add_observation_decisions(self, run_id: int, decisions: list[ObservationDecision]) -> None:
        if not decisions:
            return
        with closing(self.connect()) as conn:
            conn.executemany(
                """
                INSERT INTO analysis_decisions(
                    run_id, product_id, product_slug, source_name, source_kind,
                    url, title, raw_price, price_idr, relevance_score, included,
                    reason, parser_strategy
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        run_id,
                        decision.product_id,
                        decision.product_slug,
                        decision.source_name,
                        decision.source_kind,
                        decision.url,
                        decision.title,
                        decision.raw_price,
                        decision.price_idr,
                        decision.relevance_score,
                        int(decision.included),
                        decision.reason,
                        decision.parser_strategy,
                    )
                    for decision in decisions
                ],
            )
            conn.commit()

    def save_results(self, run_id: int, analyses: list[ProductAnalysis]) -> None:
        with closing(self.connect()) as conn:
            for analysis in analyses:
                result_cursor = conn.execute(
                    """
                    INSERT INTO product_results(
                        run_id, slug, title, language, own_price_idr, market_min_idr,
                        market_median_idr, global_average_idr, price_delta_percent,
                        alert_level, underpriced_by_idr, underpriced_by_percent,
                        recommendation, ai_summary, alert_label
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
                                product_result_id, source_name, source_kind, url,
                                title, price_idr, raw_price, currency, is_legit, relevance_score
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                result_id,
                                obs.source_name,
                                obs.source_kind,
                                obs.url,
                                obs.title,
                                obs.price_idr,
                                obs.raw_price,
                                obs.currency,
                                int(obs.is_legit),
                                obs.relevance_score,
                            ),
                        )
                _insert_price_snapshot(conn, run_id, result_id, analysis)
            conn.commit()

    def latest_run_id(self) -> int | None:
        with closing(self.connect()) as conn:
            row = conn.execute("SELECT MAX(id) FROM runs").fetchone()
        return int(row[0]) if row and row[0] is not None else None

    def inspect_run(self, run_id: int) -> dict:
        with closing(self.connect()) as conn:
            run = conn.execute(
                "SELECT id, run_at, status FROM runs WHERE id = ?",
                (run_id,),
            ).fetchone()
            events = conn.execute(
                """
                SELECT stage, severity, message, product_slug, source_name, elapsed_ms
                FROM run_events WHERE run_id = ? ORDER BY id
                """,
                (run_id,),
            ).fetchall()
            failures = conn.execute(
                """
                SELECT product_slug, source_name, status, error, fetch_backend, failure_kind
                FROM source_fetches WHERE run_id = ? AND status != 'ok'
                ORDER BY id
                """,
                (run_id,),
            ).fetchall()
        if not run:
            return {}
        return {
            "id": int(run[0]),
            "run_at": str(run[1]),
            "status": str(run[2]),
            "events": [
                {
                    "stage": row[0],
                    "severity": row[1],
                    "message": row[2],
                    "product_slug": row[3],
                    "source_name": row[4],
                    "elapsed_ms": row[5],
                }
                for row in events
            ],
            "failures": [
                {
                    "product_slug": row[0],
                    "source_name": row[1],
                    "status": row[2],
                    "error": row[3],
                    "fetch_backend": row[4],
                    "failure_kind": row[5],
                }
                for row in failures
            ],
        }


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_at TEXT NOT NULL,
            status TEXT DEFAULT 'complete',
            config_snapshot TEXT DEFAULT '{}'
        );
        CREATE TABLE IF NOT EXISTS run_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER NOT NULL REFERENCES runs(id),
            stage TEXT NOT NULL,
            severity TEXT NOT NULL,
            message TEXT NOT NULL,
            product_id TEXT DEFAULT '',
            product_slug TEXT DEFAULT '',
            source_name TEXT DEFAULT '',
            elapsed_ms INTEGER,
            details_json TEXT DEFAULT '{}'
        );
        CREATE TABLE IF NOT EXISTS source_fetches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER NOT NULL REFERENCES runs(id),
            product_id TEXT NOT NULL,
            product_slug TEXT NOT NULL,
            source_name TEXT NOT NULL,
            source_kind TEXT NOT NULL,
            url TEXT NOT NULL,
            status TEXT NOT NULL,
            started_at TEXT NOT NULL,
            elapsed_ms INTEGER NOT NULL,
            response_bytes INTEGER DEFAULT 0,
            content_hash TEXT DEFAULT '',
            artifact_path TEXT DEFAULT '',
            error TEXT DEFAULT '',
            fetch_backend TEXT DEFAULT 'stdlib',
            failure_kind TEXT DEFAULT ''
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
            ai_summary TEXT DEFAULT '',
            alert_label TEXT DEFAULT ''
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
            currency TEXT DEFAULT 'IDR',
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
        CREATE TABLE IF NOT EXISTS analysis_decisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER NOT NULL REFERENCES runs(id),
            product_id TEXT NOT NULL,
            product_slug TEXT NOT NULL,
            source_name TEXT NOT NULL,
            source_kind TEXT NOT NULL,
            url TEXT NOT NULL,
            title TEXT,
            raw_price TEXT,
            price_idr INTEGER NOT NULL,
            relevance_score REAL DEFAULT 0,
            included INTEGER NOT NULL,
            reason TEXT NOT NULL,
            parser_strategy TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_product_results_slug ON product_results(slug);
        CREATE INDEX IF NOT EXISTS idx_price_history_card_created ON price_history(card_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_run_events_run ON run_events(run_id);
        CREATE INDEX IF NOT EXISTS idx_source_fetches_run ON source_fetches(run_id);
        CREATE INDEX IF NOT EXISTS idx_analysis_decisions_run_slug ON analysis_decisions(run_id, product_slug);
        """
    )
    _ensure_columns(conn)
    _ensure_price_history_minute_index(conn)


def _ensure_columns(conn: sqlite3.Connection) -> None:
    migrations = {
        "runs": {
            "status": "TEXT DEFAULT 'complete'",
            "config_snapshot": "TEXT DEFAULT '{}'",
        },
        "product_results": {
            "global_average_idr": "INTEGER",
            "price_delta_percent": "REAL",
            "alert_level": "TEXT DEFAULT 'none'",
            "ai_summary": "TEXT DEFAULT ''",
            "alert_label": "TEXT DEFAULT ''",
        },
        "observations": {
            "currency": "TEXT DEFAULT 'IDR'",
            "relevance_score": "REAL DEFAULT 0",
        },
        "source_fetches": {
            "fetch_backend": "TEXT DEFAULT 'stdlib'",
            "failure_kind": "TEXT DEFAULT ''",
        },
    }
    for table, columns in migrations.items():
        existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        for column, definition in columns.items():
            if column not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _insert_price_snapshot(
    conn: sqlite3.Connection,
    run_id: int,
    result_id: int,
    analysis: ProductAnalysis,
) -> None:
    created_at = analysis.run_at.isoformat()
    values = (
        run_id,
        result_id,
        analysis.product.own_price_idr,
        analysis.global_average_idr,
        analysis.price_delta_percent,
        analysis.alert_level,
        _source_summary(analysis),
        created_at,
        analysis.product.slug,
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
            result_id,
            analysis.product.slug,
            analysis.product.own_price_idr,
            analysis.global_average_idr,
            analysis.price_delta_percent,
            analysis.alert_level,
            _source_summary(analysis),
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
