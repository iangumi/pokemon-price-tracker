import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pokemon_price_scheduler.infrastructure import history as history_store
from pokemon_price_scheduler.infrastructure.counterparts import (
    build_counterpart_candidates,
    convert_to_idr,
)
from pokemon_price_scheduler.models import Product


class CounterpartTests(unittest.TestCase):
    def tearDown(self):
        history_store.close_connection()

    def test_convert_to_idr_supports_usd_and_jpy(self):
        self.assertEqual(convert_to_idr(10, "USD"), (160000, 16000.0))
        self.assertEqual(convert_to_idr(1000, "JPY"), (110000, 110.0))

    def test_build_counterpart_candidates_converts_foreign_prices(self):
        product = Product(title="Pikachu SAR 001/100 Japanese", own_price_idr=1_000_000)
        observations = [
            {
                "source_name": "ebay sold",
                "source_kind": "ebay_sold",
                "url": "https://example.test/ebay",
                "title": "Pikachu SAR 001/100 English",
                "raw_price": "US $25.00",
                "price_idr": 400000,
                "relevance_score": 60,
            },
            {
                "source_name": "snkrdunk search",
                "source_kind": "snkrdunk_search",
                "url": "https://example.test/snkr",
                "title": "Pikachu SAR 001/100 Japanese",
                "raw_price": "1200",
                "price_idr": 1200,
                "relevance_score": 70,
            },
        ]

        candidates = build_counterpart_candidates(product, observations)

        by_source = {candidate["source_kind"]: candidate for candidate in candidates}
        self.assertEqual(by_source["ebay_sold"]["currency"], "USD")
        self.assertEqual(by_source["ebay_sold"]["converted_price_idr"], 400000)
        self.assertEqual(by_source["snkrdunk_search"]["currency"], "JPY")
        self.assertEqual(by_source["snkrdunk_search"]["converted_price_idr"], 132000)
        self.assertGreater(by_source["snkrdunk_search"]["confidence"], 0)

    def test_counterpart_candidates_are_persisted(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "history.sqlite3"
            candidates = [
                {
                    "source_name": "ebay sold",
                    "source_kind": "ebay_sold",
                    "source_url": "https://example.test",
                    "title": "Pikachu English",
                    "language": "English",
                    "version": "single",
                    "raw_price": "USD 10.00",
                    "currency": "USD",
                    "converted_price_idr": 160000,
                    "fx_rate_to_idr": 16000,
                    "confidence": 85,
                    "match_reason": "name match",
                }
            ]

            with patch.object(history_store, "DB_PATH", db):
                history_store.save_counterpart_candidates("pikachu", candidates)
                rows = history_store.counterpart_candidates_for_slug("pikachu")

            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["currency"], "USD")
            self.assertEqual(rows[0]["converted_price_idr"], 160000)


if __name__ == "__main__":
    unittest.main()
