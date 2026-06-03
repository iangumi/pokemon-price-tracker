import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from pokemon_price_scheduler.infrastructure.http import (
    classify_fetch_error,
    is_scrapling_available,
    resolve_fetch_backend,
    select_fetch_backend,
)
from pokemon_price_scheduler.infrastructure.scrapers import snkrdunk_search_url


class FetchBackendTests(unittest.TestCase):
    def test_auto_uses_scrapling_for_ebay_only(self):
        self.assertEqual(
            select_fetch_backend("https://www.ebay.com/sch/i.html?_nkw=pokemon"),
            "scrapling",
        )
        self.assertEqual(select_fetch_backend("https://snkrdunk.com/v3/search"), "stdlib")
        self.assertEqual(select_fetch_backend("file:///tmp/source.html"), "stdlib")

    def test_resolve_fetch_backend_falls_back_when_scrapling_missing(self):
        expected = "scrapling" if is_scrapling_available() else "stdlib"
        self.assertEqual(
            resolve_fetch_backend("https://www.ebay.com/sch/i.html?_nkw=pokemon"),
            expected,
        )

    def test_classify_fetch_error(self):
        self.assertEqual(classify_fetch_error("HTTP Error 403: Forbidden"), "http_403")
        self.assertEqual(classify_fetch_error("HTTP Error 404: Not Found"), "http_404")
        self.assertEqual(classify_fetch_error("Cloudflare Turnstile challenge"), "captcha_or_challenge")

    def test_snkrdunk_search_url_uses_v3_endpoint_and_quoted_keyword(self):
        url = snkrdunk_search_url("Mew Ex SAR ( Bubble Mew ) SAR sv4a")

        self.assertTrue(url.startswith("https://snkrdunk.com/v3/search?"))
        self.assertIn("func=all", url)
        self.assertIn("keyword=Mew+Ex+SAR+%28+Bubble+Mew+%29+SAR+sv4a", url)

    def test_migrate_snkrdunk_urls_rewrites_legacy_endpoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "products.json"
            config.write_text(
                json.dumps(
                    {
                        "products": [
                            {
                                "title": "Mew Ex SAR 347/190 sv4a - Japanese",
                                "own_price_idr": 1,
                                "sources": [
                                    {
                                        "name": "snkrdunk search",
                                        "kind": "snkrdunk_search",
                                        "url": "https://snkrdunk.com/en/trading-cards/search/result?keyword=Mew",
                                    }
                                ],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pokemon_price_scheduler",
                    "migrate-snkrdunk-urls",
                    "--config",
                    str(config),
                ],
                check=True,
                cwd=Path(__file__).resolve().parents[1],
                text=True,
                capture_output=True,
            )

            payload = json.loads(config.read_text(encoding="utf-8"))
            migrated_url = payload["products"][0]["sources"][0]["url"]
            self.assertIn("Updated 1 SnkrDunk", result.stdout)
            self.assertTrue(migrated_url.startswith("https://snkrdunk.com/v3/search?"))


if __name__ == "__main__":
    unittest.main()
