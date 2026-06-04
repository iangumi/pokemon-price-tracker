import json
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

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
                                "sources": [
                                    {
                                        "name": "tokopedia competitors",
                                        "kind": "tokopedia_find",
                                        "url": "https://example.test/search",
                                    }
                                ],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            def fake_fetch(url, timeout=30):
                return TOKOPEDIA_HTML

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
                history_count = conn.execute("SELECT COUNT(*) FROM price_history").fetchone()[0]
                snapshot = conn.execute(
                    """
                    SELECT card_id, tokopedia_price, market_avg_price, delta_percent,
                           alert_status, source_summary
                    FROM price_history
                    """
                ).fetchone()
                decisions = conn.execute(
                    "SELECT price_idr, included, reason FROM analysis_decisions ORDER BY price_idr"
                ).fetchall()

            self.assertEqual(fetch_count, 1)
            self.assertEqual(history_count, 1)
            self.assertEqual(snapshot[0], "pokemon-japanese-psa-10")
            self.assertEqual(snapshot[1], 750000)
            self.assertEqual(snapshot[2], 900000)
            self.assertIsNotNone(snapshot[3])
            self.assertEqual(snapshot[4], "none")
            self.assertIn("tokopedia competitors", snapshot[5])
            self.assertEqual(decisions[0], (16000, 0, "below_comparable_min_ratio"))
            self.assertEqual(decisions[1], (900000, 1, "included"))


if __name__ == "__main__":
    unittest.main()
