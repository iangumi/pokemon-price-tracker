import unittest

from pokemon_price_scheduler.infrastructure.marketplace_sources import (
    build_competitor_sources,
    product_with_runtime_competitor_sources,
)
from pokemon_price_scheduler.models import Product, Source


class MarketplaceSourceTests(unittest.TestCase):
    def test_build_competitor_sources_uses_manual_search_term_for_all_marketplaces(self):
        product = Product(
            title="Paldean Fates Pokemon Center Elite Trainer Box ETB Sealed",
            own_price_idr=20_000_000,
            search_terms=["Paldean Fates Pokemon"],
        )

        sources = build_competitor_sources(product)
        by_kind = {source.kind: source for source in sources}

        self.assertEqual(
            by_kind["tokopedia_find"].url,
            "https://www.tokopedia.com/find/paldean-fates-pokemon",
        )
        self.assertEqual(
            by_kind["ebay_sold"].url,
            "https://www.ebay.com/sch/i.html?_nkw=Paldean+Fates+Pokemon&LH_Sold=1&LH_Complete=1",
        )
        self.assertIn("keyword=Paldean+Fates+Pokemon", by_kind["snkrdunk_search"].url)

    def test_product_with_runtime_competitor_sources_replaces_stale_marketplace_urls_and_keeps_custom_sources(self):
        custom = Source("custom", "generic", "https://example.test/custom")
        product = Product(
            title="Pokemon Japanese PSA 10",
            own_price_idr=750_000,
            search_terms=["Pokemon"],
            sources=[
                Source("tokopedia competitors", "tokopedia_find", "https://stale.example/tokopedia"),
                Source("ebay sold", "ebay_sold", "https://stale.example/ebay"),
                Source("snkrdunk search", "snkrdunk_search", "https://stale.example/snkrdunk"),
                custom,
            ],
        )

        updated = product_with_runtime_competitor_sources(product)

        self.assertEqual([source.kind for source in updated.sources], [
            "tokopedia_find",
            "ebay_sold",
            "snkrdunk_search",
            "generic",
        ])
        self.assertNotIn("stale.example", " ".join(source.url for source in updated.sources))
        self.assertEqual(updated.sources[-1], custom)


if __name__ == "__main__":
    unittest.main()
