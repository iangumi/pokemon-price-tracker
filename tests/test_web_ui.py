import html
import json
import re
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import pokemon_price_scheduler.web as web
from pokemon_price_scheduler.config import load_config
from pokemon_price_scheduler.inventory import connect as connect_inventory, income_summary, sold_card_rows
from pokemon_price_scheduler.infrastructure import history as history_store
from pokemon_price_scheduler.history import close_connection
from pokemon_price_scheduler.models import Product, SourceResult
from pokemon_price_scheduler.scrapers import extract_store_products
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
            "AI Repricing Copilot",
            "International Counterparts",
            "Source Evidence",
            "Mark Sold",
        )
        response = self.client.get(f"/api/cards/{self.active.slug}")
        html_text = response.get_data(as_text=True)
        self.assertIn('onclick="updateSearchTerm(&quot;', html_text)
        self.assertLess(html_text.index("Price Review Snapshot"), html_text.index("Card Identity"))
        self.assertIn("identity-layout", html_text)
        self.assertIn("identity-picture-block", html_text)
        self.assertIn("identity-detail-block", html_text)

    def test_ai_repricing_advice_endpoint_handles_missing_api_key(self):
        history_db = Path(self.tmp.name) / "ai-history.sqlite3"
        with patch.object(history_store, "DB_PATH", history_db), patch.dict("os.environ", {"MINIMAX_API_KEY": ""}, clear=False):
            response = self.client.post(f"/api/cards/{self.active.slug}/ai-repricing-advice")

        self.assertEqual(response.status_code, 400)
        payload = response.get_json()
        self.assertFalse(payload["ok"])
        self.assertIn("MINIMAX_API_KEY", payload["error"])

    def test_ai_repricing_advice_endpoint_can_force_regenerate_cached_advice(self):
        history_db = Path(self.tmp.name) / "ai-force-history.sqlite3"
        generated = []

        def fake_generate(payload, client):
            generated.append(payload)
            return {
                "headline": f"Advice {len(generated)}",
                "recommended_action": "Hold price",
                "recommended_price_idr": None,
                "confidence": "medium",
                "rationale": "Fixture advice.",
                "risks": [],
                "next_steps": [],
            }

        with (
            patch.object(history_store, "DB_PATH", history_db),
            patch("pokemon_price_scheduler.ai.generate_repricing_advice", side_effect=fake_generate),
        ):
            first = self.client.post(f"/api/cards/{self.active.slug}/ai-repricing-advice").get_json()
            cached = self.client.post(f"/api/cards/{self.active.slug}/ai-repricing-advice").get_json()
            forced = self.client.post(f"/api/cards/{self.active.slug}/ai-repricing-advice?force=1").get_json()

        self.assertFalse(first["cached"])
        self.assertTrue(cached["cached"])
        self.assertFalse(forced["cached"])
        self.assertEqual(cached["record"]["advice"]["headline"], "Advice 1")
        self.assertEqual(forced["record"]["advice"]["headline"], "Advice 2")
        self.assertEqual(len(generated), 2)

    def test_update_search_term_controls_manual_refresh_sources(self):
        response = self.client.put(
            f"/api/cards/{self.active.slug}/search-term",
            json={"search_term": "Paldean Fates Pokemon"},
        )
        self.assertEqual(response.status_code, 200)

        captured_sources = []
        history_db = Path(self.tmp.name) / "refresh-history.sqlite3"

        def fake_scrape(self, source):
            captured_sources.append(source)
            return SourceResult(source=source, observations=[])

        with (
            patch.object(history_store, "DB_PATH", history_db),
            patch("pokemon_price_scheduler.infrastructure.scrapers.MarketplaceScraper.scrape", fake_scrape),
            patch("pokemon_price_scheduler.ai.attach_ai_summaries", side_effect=lambda analyses: (analyses, [])),
            patch("pokemon_price_scheduler.infrastructure.reports.write_reports"),
        ):
            web._run_refresh_bg(self.active.slug)

        source_urls = {source.kind: source.url for source in captured_sources}
        self.assertEqual(
            source_urls["tokopedia_find"],
            "https://www.tokopedia.com/find/paldean-fates-pokemon",
        )
        self.assertEqual(
            source_urls["ebay_sold"],
            "https://www.ebay.com/sch/i.html?_nkw=Paldean+Fates+Pokemon&LH_Sold=1&LH_Complete=1",
        )
        self.assertIn("keyword=Paldean+Fates+Pokemon", source_urls["snkrdunk_search"])

    def test_card_detail_renders_cached_image_in_identity_panel(self):
        with patch.object(web, "_ensure_card_image", return_value=f"/card-images/{self.active.slug}"):
            response = self.client.get(f"/api/cards/{self.active.slug}")

        self.assertEqual(response.status_code, 200)
        html_text = response.get_data(as_text=True)
        self.assertIn('class="card-image"', html_text)
        self.assertIn(f'/card-images/{self.active.slug}', html_text)

    def test_card_image_route_serves_cached_binary(self):
        image_dir = Path(self.tmp.name) / "card-images"
        image_dir.mkdir(parents=True)
        image_path = image_dir / f"{self.active.slug}.bin"
        meta_path = image_dir / f"{self.active.slug}.json"
        image_path.write_bytes(b"fakeimagebytes")
        meta_path.write_text(
            json.dumps({"content_type": "image/webp"}),
            encoding="utf-8",
        )

        with patch.object(web, "CARD_IMAGES_DIR", image_dir):
            response = self.client.get(f"/card-images/{self.active.slug}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "image/webp")
        self.assertEqual(response.get_data(), b"fakeimagebytes")

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

    def test_card_detail_falls_back_to_current_price_when_latest_snapshot_is_zero(self):
        history_rows = [
            {
                "card_id": self.active.slug,
                "tokopedia_price": 0,
                "market_avg_price": 880000,
                "delta_percent": -14.8,
                "alert_status": "none",
                "source_summary": "",
                "created_at": "2026-06-04T07:35:45+00:00",
            }
        ]

        with (
            patch.object(web, "price_history_for_slug", return_value=history_rows),
            patch.object(web, "price_trend_for_slug", side_effect=[None, None]),
        ):
            response = self.client.get(f"/api/cards/{self.active.slug}")

        self.assertEqual(response.status_code, 200)
        html_text = response.get_data(as_text=True)
        self.assertIn("Rp 750.000", html_text)
        self.assertNotIn("Rp 0", html_text)

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

    def test_add_card_uses_listing_title_when_available(self):
        listing_html = """
        <html>
          <head>
            <meta property="og:title" content="Shiny Pikachu PSA 10 | Tokopedia">
          </head>
          <body>
            <span data-testid="price">Rp 500.000</span>
          </body>
        </html>
        """
        history_db = Path(self.tmp.name) / "history.sqlite3"

        with patch.object(web, "fetch_text", return_value=listing_html), patch.object(history_store, "DB_PATH", history_db):
            close_connection()
            response = self.client.post(
                "/api/cards/add",
                json={
                    "tokopedia_url": "https://www.tokopedia.com/example/shiny-pikachu",
                    "search_keyword": "shiny pikachu psa 10",
                },
            )

        self.assertEqual(response.status_code, 201)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["slug"], "shiny-pikachu-psa-10")

        _, products = load_config(self.config_path)
        added = next((product for product in products if product.tokopedia_url == "https://www.tokopedia.com/example/shiny-pikachu"), None)
        self.assertIsNotNone(added)
        self.assertEqual(added.title, "Shiny Pikachu PSA 10")
        self.assertEqual(added.own_price_idr, 500000)

        history_rows = history_store.price_history_for_slug("shiny-pikachu-psa-10")
        self.assertEqual(len(history_rows), 1)
        self.assertEqual(history_rows[0]["tokopedia_price"], 500000)

    def test_store_parser_uses_product_specific_price_id(self):
        html_text = """
        <script>
        {"name":"First Card","product_url":"https://www.tokopedia.com/shop/first","price":{"type":"id","generated":true,"id":"Product:1.price"}}
        {"name":"Second Card","product_url":"https://www.tokopedia.com/shop/second","price":{"type":"id","generated":true,"id":"Product:2.price"}}
        "Product:1.price":{"text_idr":"Rp750.000"}
        "Product:2.price":{"text_idr":"Rp20.000.000"}
        </script>
        """

        products = extract_store_products(html_text, min_price_idr=0)

        by_title = {product["title"]: product for product in products}
        self.assertEqual(by_title["First Card"]["own_price_idr"], 750000)
        self.assertEqual(by_title["Second Card"]["own_price_idr"], 20000000)

    def test_sync_store_reconciles_prices_repairs_and_sold_status(self):
        self.config_path.write_text(
            json.dumps(
                {
                    "settings": {"min_own_price_idr": 0},
                    "products": [
                        {
                            "title": "Bad Price Card",
                            "own_price_idr": 20000000,
                            "tokopedia_url": "https://www.tokopedia.com/shop/bad-card?extParam=old",
                            "search_terms": [],
                            "sources": [],
                            "status": "active",
                            "sold_at": "",
                        },
                        {
                            "title": "Kept Card",
                            "own_price_idr": 100000,
                            "tokopedia_url": "https://www.tokopedia.com/shop/kept-card?whid=old",
                            "search_terms": [],
                            "sources": [],
                            "status": "active",
                            "sold_at": "",
                        },
                        {
                            "title": "Missing Card",
                            "own_price_idr": 300000,
                            "tokopedia_url": "https://www.tokopedia.com/shop/missing-card",
                            "search_terms": [],
                            "sources": [],
                            "status": "active",
                            "sold_at": "",
                        },
                        {
                            "title": "Already Sold Card",
                            "own_price_idr": 400000,
                            "tokopedia_url": "https://www.tokopedia.com/shop/already-sold",
                            "search_terms": [],
                            "sources": [],
                            "status": "sold",
                            "sold_at": "2026-06-01T00:00:00+00:00",
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )
        store_products = [
            {
                "title": "Bad Price Card",
                "own_price_idr": 500000,
                "tokopedia_url": "https://www.tokopedia.com/shop/bad-card?extParam=new",
            },
            {
                "title": "Kept Card",
                "own_price_idr": 125000,
                "tokopedia_url": "https://www.tokopedia.com/shop/kept-card?whid=new",
            },
            {
                "title": "Already Sold Card",
                "own_price_idr": 450000,
                "tokopedia_url": "https://www.tokopedia.com/shop/already-sold",
            },
            {
                "title": "New Store Card",
                "own_price_idr": 750000,
                "tokopedia_url": "https://www.tokopedia.com/shop/new-store-card",
            },
        ]

        with patch("pokemon_price_scheduler.store_sync.get_active_store_product_urls_with_details", return_value=store_products):
            response = self.client.post("/api/products/sync")

        self.assertEqual(response.status_code, 201)
        payload = response.get_json()
        self.assertEqual(payload["added_count"], 1)
        self.assertEqual(payload["updated_count"], 2)
        self.assertEqual(payload["repaired_count"], 1)
        self.assertEqual(payload["sold_count"], 1)

        _, products = load_config(self.config_path)
        by_title = {product.title: product for product in products}
        self.assertEqual(by_title["Bad Price Card"].own_price_idr, 500000)
        self.assertEqual(by_title["Kept Card"].own_price_idr, 125000)
        self.assertEqual(by_title["Missing Card"].status, "sold")
        self.assertTrue(by_title["Missing Card"].sold_at)
        self.assertEqual(by_title["Already Sold Card"].status, "sold")
        self.assertEqual(by_title["Already Sold Card"].own_price_idr, 400000)
        self.assertIn("New Store Card", by_title)

    def test_mark_sold_records_required_sale_fields_and_moves_to_sold_page(self):
        response = self.client.post(
            f"/api/cards/{self.active.slug}/mark-sold",
            json={
                "sold_at": "2026-06-07",
                "sold_price_idr": "900000",
                "bought_at_price_idr": "300000",
                "net_income_idr": "650000",
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["ok"])

        _, products = load_config(self.config_path)
        by_slug = {product.slug: product for product in products}
        self.assertEqual(by_slug[self.active.slug].status, "sold")
        self.assertEqual(by_slug[self.active.slug].sold_at, "2026-06-07T00:00:00+00:00")

        sold_html = self.client.get("/api/soldcards").get_data(as_text=True)
        cards_html = self.client.get("/api/cards").get_data(as_text=True)
        repricing_html = self.client.get("/api/repricing").get_data(as_text=True)
        self.assertIn("Sales Summary", sold_html)
        self.assertIn("Bought price", sold_html)
        self.assertIn("Sold price", sold_html)
        self.assertIn("Rp 300.000", sold_html)
        self.assertIn("Rp 900.000", sold_html)
        self.assertIn("Rp 650.000", sold_html)
        self.assertIn(self.active.slug, sold_html)
        self.assertNotIn(self.active.slug, cards_html)
        self.assertNotIn(self.active.slug, repricing_html)

        rows = sold_card_rows(web._inventory_db_path())
        self.assertEqual(rows[0]["bought_at_price_idr"], 300000)
        self.assertEqual(rows[0]["sold_price_idr"], 900000)
        self.assertEqual(rows[0]["net_income_idr"], 650000)
        summary = income_summary(web._inventory_db_path())
        self.assertEqual(summary["sold_count"], 1)
        self.assertEqual(summary["net_income_idr"], 650000)

    def test_mark_sold_requires_bought_price_and_net_income(self):
        response = self.client.post(
            f"/api/cards/{self.active.slug}/mark-sold",
            json={"sold_at": "2026-06-07", "net_income_idr": "650000", "bought_at_price_idr": "300000"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Sold price is required", response.get_json()["error"])

    def test_existing_sold_card_sale_details_can_be_updated(self):
        response = self.client.post(
            f"/api/cards/{self.sold.slug}/sale-details",
            json={
                "sold_at": "2026-06-07",
                "sold_price_idr": "700000",
                "bought_at_price_idr": "200000",
                "net_income_idr": "450000",
            },
        )

        self.assertEqual(response.status_code, 200)
        _, products = load_config(self.config_path)
        by_slug = {product.slug: product for product in products}
        self.assertEqual(by_slug[self.sold.slug].status, "sold")
        self.assertEqual(by_slug[self.sold.slug].sold_at, "2026-06-07T00:00:00+00:00")

        sold_html = self.client.get("/api/soldcards").get_data(as_text=True)
        self.assertIn("Rp 200.000", sold_html)
        self.assertIn("Rp 700.000", sold_html)
        self.assertIn("Rp 450.000", sold_html)
        self.assertIn("Edit Sale", sold_html)

    def test_restock_keeps_sold_sale_history_and_creates_active_listing_lifecycle(self):
        self.client.post(
            f"/api/cards/{self.active.slug}/mark-sold",
            json={
                "sold_at": "2026-06-07",
                "sold_price_idr": "900000",
                "bought_at_price_idr": "300000",
                "net_income_idr": "650000",
            },
        )

        response = self.client.put(f"/api/cards/{self.active.slug}/revert-sold")
        self.assertEqual(response.status_code, 200)

        _, products = load_config(self.config_path)
        product = next(p for p in products if p.slug == self.active.slug)
        self.assertEqual(product.status, "active")

        with closing(connect_inventory(web._inventory_db_path())) as conn:
            lifecycles = conn.execute(
                "SELECT status, lifecycle FROM listings WHERE slug = ? ORDER BY id",
                (self.active.slug,),
            ).fetchall()
            sale_count = conn.execute(
                "SELECT COUNT(*) FROM sales WHERE slug = ? AND net_income_idr = 650000",
                (self.active.slug,),
            ).fetchone()[0]

        self.assertEqual(lifecycles, [("sold", 1), ("active", 2)])
        self.assertEqual(sale_count, 1)

    def test_sync_store_dedupes_active_and_sold_duplicates(self):
        self.config_path.write_text(
            json.dumps(
                {
                    "settings": {"min_own_price_idr": 0},
                    "products": [
                        {
                            "title": "Mew Duplicate",
                            "own_price_idr": 1000000,
                            "tokopedia_url": "https://www.tokopedia.com/shop/mew-card?whid=old",
                            "search_terms": [],
                            "sources": [],
                            "status": "sold",
                            "sold_at": "2026-05-22T00:00:00+00:00",
                        },
                        {
                            "title": "Mew Duplicate",
                            "own_price_idr": 1000000,
                            "tokopedia_url": "https://www.tokopedia.com/shop/mew-card?extParam=new",
                            "search_terms": [],
                            "sources": [],
                            "status": "active",
                            "sold_at": "",
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )
        store_products = [
            {
                "title": "Mew Duplicate",
                "own_price_idr": 1000000,
                "tokopedia_url": "https://www.tokopedia.com/shop/mew-card?src=shop",
            }
        ]

        with patch("pokemon_price_scheduler.store_sync.get_active_store_product_urls_with_details", return_value=store_products):
            response = self.client.post("/api/products/sync")

        self.assertEqual(response.status_code, 201)
        payload = response.get_json()
        self.assertEqual(payload["deduped_count"], 1)

        _, products = load_config(self.config_path)
        self.assertEqual(len(products), 1)
        self.assertEqual(products[0].status, "active")

        cards_html = self.client.get("/api/cards").get_data(as_text=True)
        sold_html = self.client.get("/api/soldcards").get_data(as_text=True)
        self.assertIn("mew-duplicate-raw-nm", cards_html)
        self.assertNotIn("mew-duplicate-raw-nm", sold_html)

    def test_sync_store_dedupes_active_active_and_sold_sold_duplicates(self):
        self.config_path.write_text(
            json.dumps(
                {
                    "settings": {"min_own_price_idr": 0},
                    "products": [
                        {
                            "title": "Active Duplicate Old",
                            "own_price_idr": 100000,
                            "tokopedia_url": "https://www.tokopedia.com/shop/active-dupe?old=1",
                            "search_terms": [],
                            "sources": [],
                            "status": "active",
                            "sold_at": "",
                        },
                        {
                            "title": "Active Duplicate New",
                            "own_price_idr": 200000,
                            "tokopedia_url": "https://www.tokopedia.com/shop/active-dupe?new=1",
                            "search_terms": [],
                            "sources": [],
                            "status": "active",
                            "sold_at": "",
                        },
                        {
                            "title": "Sold Duplicate Old",
                            "own_price_idr": 300000,
                            "tokopedia_url": "https://www.tokopedia.com/shop/sold-dupe?old=1",
                            "search_terms": [],
                            "sources": [],
                            "status": "sold",
                            "sold_at": "2026-05-01T00:00:00+00:00",
                        },
                        {
                            "title": "Sold Duplicate New",
                            "own_price_idr": 400000,
                            "tokopedia_url": "https://www.tokopedia.com/shop/sold-dupe?new=1",
                            "search_terms": [],
                            "sources": [],
                            "status": "sold",
                            "sold_at": "2026-06-01T00:00:00+00:00",
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )
        store_products = [
            {
                "title": "Active Duplicate New",
                "own_price_idr": 200000,
                "tokopedia_url": "https://www.tokopedia.com/shop/active-dupe",
            },
            {
                "title": "Sold Duplicate New",
                "own_price_idr": 400000,
                "tokopedia_url": "https://www.tokopedia.com/shop/sold-dupe",
            },
        ]

        with patch("pokemon_price_scheduler.store_sync.get_active_store_product_urls_with_details", return_value=store_products):
            response = self.client.post("/api/products/sync")

        self.assertEqual(response.status_code, 201)
        payload = response.get_json()
        self.assertEqual(payload["deduped_count"], 2)

        _, products = load_config(self.config_path)
        by_title = {product.title: product for product in products}
        self.assertEqual(len(products), 2)
        self.assertIn("Active Duplicate New", by_title)
        self.assertIn("Sold Duplicate New", by_title)
        self.assertEqual(by_title["Active Duplicate New"].status, "active")
        self.assertEqual(by_title["Sold Duplicate New"].status, "sold")

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

    def test_opportunities_buy_list_can_create_and_render_detail(self):
        response = self.client.post(
            "/api/opportunities",
            json={
                "card_name": "Lisia's Appeal",
                "card_rarity": "SAR",
                "card_language": "Japanese",
                "source": "Tokopedia seller",
                "link": "https://example.test/lisia",
                "price_idr": "1500000",
            },
        )

        self.assertEqual(response.status_code, 201)
        slug = response.get_json()["slug"]
        self.assert_fragment_has(
            "/api/opportunities",
            "Buy List Opportunities",
            "Add Buy List Card",
            "opportunityLink",
            "Lisia",
            "1500000",
        )
        self.assert_fragment_has(
            f"/api/opportunities/{slug}",
            "Opportunity Snapshot",
            "Card Opportunity Detail",
            "Convert to Inventory",
            "Open Source",
        )

    def test_convert_opportunity_to_inventory_only(self):
        created = self.client.post(
            "/api/opportunities",
            json={
                "card_name": "Misty's Favor",
                "card_rarity": "SR",
                "card_language": "Japanese",
                "source": "eBay",
                "link": "https://example.test/misty",
                "price_idr": "2000000",
            },
        ).get_json()

        response = self.client.post(
            f"/api/opportunities/{created['slug']}/convert",
            json={"bought_at_price_idr": "1900000"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.get_json()["created_listing"])
        detail_html = self.client.get(f"/api/opportunities/{created['slug']}").get_data(as_text=True)
        inventory_html = self.client.get("/api/inventory").get_data(as_text=True)
        cards_html = self.client.get("/api/cards").get_data(as_text=True)

        self.assertIn("Converted", detail_html)
        self.assertIn("Owned Inventory", inventory_html)
        self.assertIn("1900000", inventory_html)
        self.assertIn("Misty", inventory_html)
        self.assertNotIn(created["slug"], cards_html)

    def test_convert_opportunity_to_active_listing_when_listing_fields_are_present(self):
        created = self.client.post(
            "/api/opportunities",
            json={
                "card_name": "Erika's Invitation",
                "card_rarity": "SAR",
                "card_language": "Japanese",
                "source": "SNKRDUNK",
                "link": "https://example.test/erika",
                "price_idr": "2500000",
            },
        ).get_json()

        response = self.client.post(
            f"/api/opportunities/{created['slug']}/convert",
            json={
                "bought_at_price_idr": "2400000",
                "tokopedia_url": "https://www.tokopedia.com/shop/erika-invitation",
                "listing_price_idr": "3000000",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["created_listing"])

        _, products = load_config(self.config_path)
        added = next((p for p in products if p.tokopedia_url == "https://www.tokopedia.com/shop/erika-invitation"), None)
        self.assertIsNotNone(added)
        self.assertEqual(added.own_price_idr, 3000000)

        cards_html = self.client.get("/api/cards").get_data(as_text=True)
        inventory_html = self.client.get("/api/inventory").get_data(as_text=True)
        self.assertIn(added.slug, cards_html)
        self.assertIn("Owned Inventory", inventory_html)
        self.assertIn("listed", inventory_html)

    def test_inventory_page_combines_active_and_sold_listing_quantities(self):
        html_text = self.client.get("/api/inventory").get_data(as_text=True)

        self.assertIn("Owned Inventory", html_text)
        self.assertIn(self.active.slug, html_text)
        self.assertIn(self.sold.slug, html_text)
        self.assertIn("active", html_text)
        self.assertIn("sold", html_text)
        self.assertIn("Qty", html_text)

    def test_opportunities_page_uses_grid_shell(self):
        self.client.post(
            "/api/opportunities",
            json={
                "card_name": "Pikachu",
                "card_rarity": "PROMO",
                "card_language": "Japanese",
                "source": "Tokopedia",
                "link": "https://example.test/pikachu",
                "price_idr": "500000",
            },
        )
        self.assert_fragment_has(
            "/api/opportunities",
            "Buy List Opportunities",
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
            self.assertIn("Store Listings", html_text)
            self.assertIn("Inventory", html_text)
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
