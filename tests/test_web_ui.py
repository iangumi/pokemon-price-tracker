import html
import json
import re
import tempfile
import unittest
from pathlib import Path

import pokemon_price_scheduler.web as web
from pokemon_price_scheduler.history import close_connection
from pokemon_price_scheduler.models import Product
from pokemon_price_scheduler.ui_components import repricing_queue_fragment


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
            "cards-page",
            "cards-data-grid",
            "toolbar",
            "ag-grid-host",
            "ag-theme-quartz",
            "data-columns",
            "data-rows",
            "alertBadge",
            "moneyValue",
            "percentValue",
        )

    def test_cards_grid_mount_has_theme_class(self):
        response = self.client.get("/api/cards")
        self.assertEqual(response.status_code, 200)
        html_text = response.get_data(as_text=True)
        self.assertIn('class="ag-grid-host ag-theme-quartz cards-data-grid"', html_text)
        self.assertIn('class="table-shell grid-shell cards-data-grid"', html_text)

    def test_cards_columns_use_flex_sizing(self):
        response = self.client.get("/api/cards")
        self.assertEqual(response.status_code, 200)
        html_text = response.get_data(as_text=True)
        match = re.search(r'data-columns="([^"]*)"', html_text)
        self.assertIsNotNone(match)
        columns = json.loads(html.unescape(match.group(1)))
        by_field = {column["field"]: column for column in columns}

        self.assertEqual(by_field["title"]["flex"], 3)
        self.assertEqual(by_field["title"]["minWidth"], 420)
        self.assertTrue(by_field["title"]["wrapText"])
        self.assertTrue(by_field["title"]["autoHeight"])
        self.assertEqual(by_field["own_price"]["flex"], 1)
        self.assertNotIn("width", by_field["own_price"])

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
            "Latest Tokopedia price",
            "Latest market avg",
            "Suggested Tokopedia Price",
            "Price History",
            "Card Identity",
            "Source Evidence",
        )

    def test_repricing_queue_route_uses_panel(self):
        self.assert_fragment_has(
            "/api/repricing",
            "Repricing Queue",
        )

    def test_repricing_queue_fragment_renders_actions_and_suggestions(self):
        html_text = repricing_queue_fragment(
            [
                {
                    "title": "Pokemon Japanese PSA 10",
                    "slug": "pokemon-japanese-psa-10",
                    "tokopedia_price": 750000,
                    "market_avg_price": 900000,
                    "delta_percent": -16.7,
                    "suggested_quick_sale": 828000,
                    "suggested_normal": 882000,
                    "suggested_max_profit": 945000,
                    "recommended_action": "Raise price",
                },
                {
                    "title": "No Market Card",
                    "slug": "no-market-card",
                    "tokopedia_price": 500000,
                    "market_avg_price": None,
                    "delta_percent": None,
                    "suggested_quick_sale": None,
                    "suggested_normal": None,
                    "suggested_max_profit": None,
                    "recommended_action": "Missing market data",
                },
            ]
        )
        self.assertIn("Repricing Queue", html_text)
        self.assertIn("Need price decrease", html_text)
        self.assertIn("Need price increase", html_text)
        self.assertIn("Filter", html_text)
        self.assertIn("Sort", html_text)
        self.assertIn("filterRepricing('Lower price')", html_text)
        self.assertIn("sortRepricing('delta_desc')", html_text)
        self.assertIn("Highest card price", html_text)
        self.assertIn("actionBadge", html_text)
        self.assertIn("suggestedMoney", html_text)
        self.assertIn("Missing market data", html_text)

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
            self.assertIn('/vendor/ag-grid/ag-grid.css', html_text)
            self.assertIn('/vendor/ag-grid/ag-theme-quartz.css', html_text)
            self.assertIn("colorSchemeDarkBlue", html_text)
            self.assertIn("themeQuartz.withPart", html_text)
            self.assertIn("Repricing Queue", html_text)
            self.assertIn("actionBadge", html_text)
            self.assertIn("suggestedMoney", html_text)
            self.assertIn("filterRepricing", html_text)
            self.assertIn("sortRepricing", html_text)
            self.assertIn("_agGridById", html_text)
            self.assertIn("autoSizeStrategy", html_text)
            self.assertIn("minWidth: 140", html_text)
            self.assertIn("resizable: true", html_text)
            self.assertIn("--ag-foreground-color: #e5e7eb", html_text)
            self.assertIn("--ag-background-color: #111827", html_text)
            self.assertIn("--ag-header-background-color: #1f2937", html_text)
            self.assertIn("--ag-row-hover-color: #243244", html_text)
            self.assertIn(".cards-page", html_text)
            self.assertIn("height: calc(100vh - 260px)", html_text)
            self.assertIn("max-width: none", html_text)
        finally:
            response.close()


if __name__ == "__main__":
    unittest.main()
