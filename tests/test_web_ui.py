import html
import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pokemon_price_scheduler.web as web
from pokemon_price_scheduler.infrastructure import history as history_store
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
            "Live Store Signals",
            "metric-grid",
            "metric-card",
            "panel",
            "Active Cards",
            "Repricing Queue",
            "dashboard-preview-table",
            "Rp 0.8M",
        )
        response = self.client.get("/api/dashboard")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("Source Health", response.get_data(as_text=True))

    def test_reports_page_contains_source_health_and_report_links(self):
        self.assert_fragment_has(
            "/api/reports",
            "Report Files",
            "Source Health",
            "latest.md",
            "latest.csv",
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

    def test_card_detail_renders_price_history_metrics_table_and_chart(self):
        history_rows = [
            {
                "card_id": self.active.slug,
                "tokopedia_price": 760000,
                "market_avg_price": 900000,
                "delta_percent": -15.6,
                "alert_status": "none",
                "source_summary": "",
                "created_at": "2026-06-04T07:35:45+00:00",
            },
            {
                "card_id": self.active.slug,
                "tokopedia_price": 750000,
                "market_avg_price": 880000,
                "delta_percent": -14.8,
                "alert_status": "none",
                "source_summary": "",
                "created_at": "2026-06-03T07:35:45+00:00",
            },
        ]
        reports_dir = Path(self.tmp.name) / "reports"
        chart_dir = reports_dir / "charts"
        chart_dir.mkdir(parents=True)
        (chart_dir / f"{self.active.slug}.svg").write_text("<svg></svg>", encoding="utf-8")

        with (
            patch.object(web, "REPORTS_DIR", reports_dir),
            patch.object(web, "price_history_for_slug", return_value=history_rows),
            patch.object(web, "price_trend_for_slug", side_effect=[1.2, 3.4]),
        ):
            response = self.client.get(f"/api/cards/{self.active.slug}")

        self.assertEqual(response.status_code, 200)
        html_text = response.get_data(as_text=True)
        self.assertIn("Latest Tokopedia price", html_text)
        self.assertIn("Rp 760.000", html_text)
        self.assertIn("Latest market avg", html_text)
        self.assertIn("Rp 900.000", html_text)
        self.assertIn("+1.2%", html_text)
        self.assertIn("+3.4%", html_text)
        self.assertIn("price-history-chart", html_text)
        self.assertIn("data-rows", html_text)

    def test_repricing_queue_route_uses_panel(self):
        self.assert_fragment_has(
            "/api/repricing",
            "Repricing Queue",
        )

    def test_repricing_queue_filters_to_active_slugs(self):
        products = [
            {
                "title": "Active Card",
                "slug": "active-card",
                "own_price_idr": 100000,
                "global_average_idr": 120000,
                "price_delta_percent": -16.7,
            },
            {
                "title": "Test Card",
                "slug": "test-slug",
                "own_price_idr": 500000,
                "global_average_idr": 400000,
                "price_delta_percent": 25.0,
            },
        ]
        with patch.object(history_store, "get_all_products_with_trend", return_value=products):
            rows = history_store.repricing_queue({"active-card"})

        self.assertEqual([row["slug"] for row in rows], ["active-card"])

    def test_repricing_queue_route_uses_active_tokopedia_listings(self):
        captured = {}

        def fake_repricing_queue(active_slugs):
            captured["active_slugs"] = active_slugs
            return [
                {
                    "title": "Pokemon Japanese PSA 10",
                    "slug": self.active.slug,
                    "tokopedia_price": 750000,
                    "market_avg_price": 900000,
                    "delta_percent": -16.7,
                    "suggested_quick_sale": 828000,
                    "suggested_normal": 882000,
                    "suggested_max_profit": 945000,
                    "recommended_action": "Raise price",
                }
            ]

        with patch.object(web, "repricing_queue", side_effect=fake_repricing_queue):
            response = self.client.get("/api/repricing")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(captured["active_slugs"], {self.active.slug})
        self.assertNotIn(self.sold.slug, captured["active_slugs"])

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

    def test_index_uses_retro_handheld_grid_theme(self):
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
            self.assertIn("navigateTo('/reports')", html_text)
            self.assertIn("/api/reports", html_text)
            self.assertIn('class="nav-icon"', html_text)
            self.assertIn("_agGridById", html_text)
            self.assertIn("autoSizeStrategy", html_text)
            self.assertIn("minWidth: 140", html_text)
            self.assertIn("resizable: true", html_text)
            self.assertIn("--case: #d8d3b7", html_text)
            self.assertIn("--lcd: #a9bd68", html_text)
            self.assertIn("--button: #7b3f73", html_text)
            self.assertIn("--ag-background-color: rgba(199, 216, 138, 0.78)", html_text)
            self.assertIn("--ag-foreground-color: var(--ink)", html_text)
            self.assertIn("--ag-header-background-color: var(--lcd-light)", html_text)
            self.assertIn("--ag-header-foreground-color: #000", html_text)
            self.assertIn("--ag-row-hover-color: rgba(24, 35, 19, 0.16)", html_text)
            self.assertIn("rowHeight: isCardsGrid ? 72 : 44", html_text)
            self.assertIn("-webkit-line-clamp: 2", html_text)
            self.assertIn(".cards-page", html_text)
            self.assertIn("height: calc(100vh - 260px)", html_text)
            self.assertIn("max-width: none", html_text)
        finally:
            response.close()

    def test_retro_preview_static_page_loads(self):
        response = self.client.get("/retro-preview.html")
        try:
            self.assertEqual(response.status_code, 200)
            html_text = response.get_data(as_text=True)
            self.assertIn("Retro Preview - Pokemon Price Tracker", html_text)
            self.assertIn("/vendor/ag-grid/ag-grid.css", html_text)
            self.assertIn("/alpine.min.js", html_text)
            self.assertIn("Minimal retro handheld skin concept", html_text)
            self.assertIn("Preview-only screen. No API calls are made.", html_text)
        finally:
            response.close()


if __name__ == "__main__":
    unittest.main()
