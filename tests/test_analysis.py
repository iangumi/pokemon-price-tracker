import unittest
from datetime import datetime, timezone

from pokemon_price_scheduler.analyze import analyze_product
from pokemon_price_scheduler.models import PriceObservation, Product, Source, SourceResult


class AnalysisTests(unittest.TestCase):
    def test_analysis_ignores_implausible_scrape_noise(self):
        product = Product(title="Pokemon Japanese PSA 10", own_price_idr=750000)
        source = Source(name="tokopedia", kind="tokopedia_find", url="https://example.com")
        result = SourceResult(
            source=source,
            observations=[
                PriceObservation("tokopedia", "tokopedia_find", source.url, 16000),
                PriceObservation("tokopedia", "tokopedia_find", source.url, 900000),
                PriceObservation("tokopedia", "tokopedia_find", source.url, 134_000_000),
            ],
        )

        analysis = analyze_product(
            product,
            [result],
            datetime(2026, 5, 20, tzinfo=timezone.utc),
            {"comparable_min_ratio_to_own": 0.35, "comparable_max_ratio_to_own": 8},
        )

        self.assertEqual(analysis.market_median_idr, 900000)
        self.assertEqual(analysis.legit_market_prices, [900000])


if __name__ == "__main__":
    unittest.main()
