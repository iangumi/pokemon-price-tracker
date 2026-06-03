import html
import json
import re
import tempfile
import unittest
from pathlib import Path

import pokemon_price_scheduler.web as web
from pokemon_price_scheduler.history import close_connection
from pokemon_price_scheduler.models import Product


class WebUiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.original_config = web.CONFIG_PATH
        self.config_path = Path(self.tmp.name) / "products.json"
        self.active = Product(
            title="Pokemon Japanese PSA 10",
            own_price_idr=750000,
            tokopedia_url="file:///tmp/card.html",
            search_terms=["Pokemon Japanese PSA 10"],
        )
        self.sold = Product(
            title="Sold Pokemon Card",
            own_price_idr=500000,
            tokopedia_url="https://example.test/sold",
            status="sold",
            sold_at="2026-06-01T00:00:00+00:00",
        )
        self.config_path.write_text(
            json.dumps(
                {
                    "settings": {"min_own_price_idr": 0},
                    "products": [
                        {
                            "title": self.active.title,
                            "own_price_idr": self.active.own_price_idr,
                            "tokopedia_url": self.active.tokopedia_url,
                            "search_terms": self.active.search_terms,
                            "sources": [],
                        },
                        {
                            "title": self.sold.title,
                            "own_price_idr": self.sold.own_price_idr,
                            "tokopedia_url": self.sold.tokopedia_url,
                            "status": self.sold.status,
                            "sold_at": self.sold.sold_at,
                            "sources": [],
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )
        web.CONFIG_PATH = self.config_path
        self.client = web.app.test_client()

    def tearDown(self):
        web.CONFIG_PATH = self.original_config
        close_connection()
        self.tmp.cleanup()

    def assert_fragment_has(self, path, *needles):
        response = self.client.get(path)
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        for needle in needles:
            self.assertIn(needle, html)
        self.assertNotIn("class-=", html)

    def test_dashboard_uses_shared_trading_desk_components(self):
        self.assert_fragment_has(
            "/api/dashboard",
            "metric-grid",
            "metric-card",
            "panel",
            "Source Health",
        )

    def test_cards_uses_shared_table_and_toolbar(self):
        self.assert_fragment_has(
            "/api/cards",
            "toolbar",
            "ag-grid-host",
            "data-columns",
            "data-rows",
            "alertBadge",
            "moneyValue",
            "percentValue",
        )

    def test_cards_omits_columns_that_are_empty_for_every_row(self):
        response = self.client.get("/api/cards")
        self.assertEqual(response.status_code, 200)
        html_text = response.get_data(as_text=True)
        match = re.search(r'data-columns="([^"]*)"', html_text)
        self.assertIsNotNone(match)
        columns = json.loads(html.unescape(match.group(1)))
        fields = {column["field"] for column in columns}
        self.assertIn("title", fields)
        self.assertIn("alert", fields)
        self.assertNotIn("market_trend", fields)

    def test_card_detail_uses_shared_panels_and_field_row(self):
        self.assert_fragment_has(
            f"/api/cards/{self.active.slug}",
            "toolbar",
            "field-row",
            "Card Identity",
            "Source Evidence",
        )

    def test_sold_cards_use_product_card_component(self):
        self.assert_fragment_has(
            "/api/soldcards",
            "product-card",
            "Mark Active",
        )

    def test_opportunities_uses_review_queue_panel(self):
        self.assert_fragment_has(
            "/api/opportunities",
            "Opportunity Review Queue",
            "ag-grid-host",
            "data-columns",
            "data-rows",
        )

    def test_ag_grid_assets_are_served_locally(self):
        response = self.client.get("/vendor/ag-grid/ag-grid-community.min.js")
        try:
            self.assertEqual(response.status_code, 200)
            self.assertIn("createGrid", response.get_data(as_text=True))
        finally:
            response.close()

    def test_index_uses_ag_grid_dark_blue_theme(self):
        response = self.client.get("/")
        try:
            self.assertEqual(response.status_code, 200)
            html_text = response.get_data(as_text=True)
            self.assertIn("colorSchemeDarkBlue", html_text)
            self.assertIn("themeQuartz.withPart", html_text)
        finally:
            response.close()


if __name__ == "__main__":
    unittest.main()
