import json
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from pokemon_price_scheduler.models import Product, ProductAnalysis
from pokemon_price_scheduler.v2.config import load_validated_config
from pokemon_price_scheduler.v2.models import ConfigError
from pokemon_price_scheduler.v2.pipeline import PipelineOptions, RunPipeline
from pokemon_price_scheduler.v2.storage import TraceStore


TOKOPEDIA_HTML = """
<div data-testid="divFindProduct#1">
  <a href="https://www.tokopedia.com/seller/card-a">
    <span>Pokemon Japanese PSA 10</span>
    <span>Rp 900.000</span>
  </a>
</div>
<div data-testid="divFindProduct#2">
  <a href="https://www.tokopedia.com/seller/card-b">
    <span>Pokemon Japanese PSA 10</span>
    <span>Rp 16.000</span>
  </a>
</div>
"""


class V2PipelineTests(unittest.TestCase):
    def test_config_validation_rejects_missing_title(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "products.json"
            config.write_text(
                json.dumps({"products": [{"own_price_idr": 750000}]}),
                encoding="utf-8",
            )

            with self.assertRaises(ConfigError):
                load_validated_config(config)

    def test_pipeline_persists_trace_and_observation_decisions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = root / "products.json"
            db = root / "history.sqlite3"
            reports = root / "reports"
            artifacts = root / "runs"
            config.write_text(
                json.dumps(
                    {
                        "settings": {
                            "min_own_price_idr": 0,
                            "comparable_min_ratio_to_own": 0.35,
                            "comparable_max_ratio_to_own": 8,
                            "tokopedia_scam_floor_ratio": 0,
                            "tokopedia_min_legit_results": 0,
                        },
                        "products": [
                            {
                                "title": "Pokemon Japanese PSA 10",
                                "own_price_idr": 750000,
                                "tokopedia_url": "https://www.tokopedia.com/store/card-a",
                                "search_terms": ["Pokemon Japanese PSA 10"],
                                "sources": [
                                    {
                                        "name": "tokopedia competitors",
                                        "kind": "tokopedia_find",
                                        "url": "https://example.test/search",
                                    }
                                ],
                            },
                            {
                                "title": "No Market Card",
                                "own_price_idr": 500000,
                                "tokopedia_url": "https://www.tokopedia.com/store/card-b",
                                "sources": [],
                            },
                            {
                                "title": "Config Only Card",
                                "own_price_idr": 600000,
                                "sources": [],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            fetched_urls = []

            def fake_fetch(url, timeout=30):
                fetched_urls.append(url)
                if "tokopedia.com/find/pokemon-japanese-psa-10" in url:
                    return TOKOPEDIA_HTML
                return ""

            result = RunPipeline(
                PipelineOptions(
                    config_path=config,
                    db_path=db,
                    report_dir=reports,
                    artifact_dir=artifacts,
                    debug=True,
                    detect_sold=False,
                ),
                fetcher=fake_fetch,
            ).run()

            store = TraceStore(db)
            trace = store.inspect_run(result.run_id)

            self.assertEqual(trace["status"], "complete")
            self.assertTrue((reports / "latest.md").exists())
            self.assertTrue(list((artifacts / str(result.run_id) / "sources").glob("*.html")))

            with closing(store.connect()) as conn:
                fetch_count = conn.execute("SELECT COUNT(*) FROM source_fetches").fetchone()[0]
                fetch_urls = [
                    row[0]
                    for row in conn.execute("SELECT url FROM source_fetches ORDER BY id").fetchall()
                ]
                history_count = conn.execute("SELECT COUNT(*) FROM price_history").fetchone()[0]
                snapshots = conn.execute(
                    """
                    SELECT card_id, tokopedia_price, market_avg_price, delta_percent,
                           alert_status, source_summary
                    FROM price_history
                    ORDER BY card_id
                    """
                ).fetchall()
                decisions = conn.execute(
                    "SELECT price_idr, included, reason FROM analysis_decisions ORDER BY price_idr"
                ).fetchall()

            self.assertEqual(fetch_count, 6)
            self.assertIn("https://www.tokopedia.com/find/pokemon-japanese-psa-10", fetch_urls)
            self.assertIn(
                "https://www.ebay.com/sch/i.html?_nkw=Pokemon+Japanese+PSA+10&LH_Sold=1&LH_Complete=1",
                fetch_urls,
            )
            self.assertTrue(any("snkrdunk.com/v3/search" in url and "keyword=Pokemon+Japanese+PSA+10" in url for url in fetch_urls))
            self.assertNotIn("https://example.test/search", fetch_urls)
            self.assertEqual(history_count, 2)
            snapshots_by_slug = {row[0]: row for row in snapshots}
            snapshot = snapshots_by_slug["pokemon-japanese-psa-10"]
            missing_market_snapshot = snapshots_by_slug["no-market-card-raw-nm"]
            self.assertEqual(snapshot[1], 750000)
            self.assertEqual(snapshot[2], 900000)
            self.assertIsNotNone(snapshot[3])
            self.assertEqual(snapshot[4], "none")
            self.assertIn("tokopedia competitors", snapshot[5])
            self.assertEqual(missing_market_snapshot[1], 500000)
            self.assertIsNone(missing_market_snapshot[2])
            self.assertIsNone(missing_market_snapshot[3])
            self.assertEqual(missing_market_snapshot[4], "none")
            self.assertEqual(decisions[0], (16000, 0, "below_comparable_min_ratio"))
            self.assertEqual(decisions[1], (900000, 1, "included"))

    def test_price_history_updates_same_card_within_same_minute(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "history.sqlite3"
            store = TraceStore(db)
            run_at = datetime(2026, 6, 4, 7, 35, 10, tzinfo=timezone.utc)
            later_same_minute = datetime(2026, 6, 4, 7, 35, 45, tzinfo=timezone.utc)
            product = Product(
                title="Pokemon Japanese PSA 10",
                own_price_idr=750000,
                tokopedia_url="https://www.tokopedia.com/store/card-a",
            )
            first_run = store.create_run(run_at.isoformat(), {})
            second_run = store.create_run(later_same_minute.isoformat(), {})

            store.save_results(
                first_run,
                [
                    ProductAnalysis(
                        product=product,
                        run_at=run_at,
                        source_results=[],
                        legit_market_prices=[],
                        market_min_idr=None,
                        market_median_idr=None,
                        global_average_idr=900000,
                        price_delta_percent=-16.7,
                        alert_level="none",
                        underpriced_by_idr=None,
                        underpriced_by_percent=None,
                        recommendation="Market data captured",
                    )
                ],
            )
            store.save_results(
                second_run,
                [
                    ProductAnalysis(
                        product=product,
                        run_at=later_same_minute,
                        source_results=[],
                        legit_market_prices=[],
                        market_min_idr=None,
                        market_median_idr=None,
                        global_average_idr=950000,
                        price_delta_percent=-21.1,
                        alert_level="amber",
                        underpriced_by_idr=None,
                        underpriced_by_percent=None,
                        recommendation="Market data captured",
                    )
                ],
            )

            with closing(store.connect()) as conn:
                rows = conn.execute(
                    """
                    SELECT run_id, tokopedia_price, market_avg_price, delta_percent,
                           alert_status, created_at
                    FROM price_history
                    """
                ).fetchall()
                indexes = conn.execute(
                    """
                    SELECT name
                    FROM sqlite_master
                    WHERE type = 'index' AND name = 'idx_price_history_card_minute'
                    """
                ).fetchall()

            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0][0], second_run)
            self.assertEqual(rows[0][1], 750000)
            self.assertEqual(rows[0][2], 950000)
            self.assertEqual(rows[0][3], -21.1)
            self.assertEqual(rows[0][4], "amber")
            self.assertEqual(rows[0][5], later_same_minute.isoformat())
            self.assertEqual(len(indexes), 1)


if __name__ == "__main__":
    unittest.main()
