from __future__ import annotations

import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

from flask import Flask, Response, jsonify, request

from .history import get_all_products_with_trend, get_observations_for_slug, history_for_slug
from .models import Product, Source, utc_now
from .reports import idr, pct
from .ui_components import (
    cards_fragment,
    card_detail_fragment,
    dashboard_fragment,
    opportunities_fragment,
    sold_cards_fragment,
)
from .v2.storage import TraceStore

BASE_DIR = Path(__file__).parent.parent
STATIC_DIR = BASE_DIR / "static"
REPORTS_DIR = BASE_DIR / "reports"
CONFIG_PATH = BASE_DIR / "config" / "products.json"

app = Flask(__name__, template_folder=str(REPORTS_DIR), static_folder=str(STATIC_DIR), static_url_path="")


# Track background scheduler process pid
_scheduler_pid = None
_scheduler_proc = None
_refreshing_slugs: set = set()


def _run_scheduler_bg(proc: subprocess.Popen, log_handle):
    global _scheduler_pid, _scheduler_proc
    try:
        proc.wait()
    finally:
        log_handle.close()
        _scheduler_pid = None
        _scheduler_proc = None


# ─── Static shell routes ──────────────────────────────────────────────────────

@app.route("/test.htm")
def test_page():
    return """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>HTMX Test</title>
  <script src="https://unpkg.com/htmx.org@1.9.12/dist/htmx.min.js"></script>
</head>
<body>
  <h1>Test Page</h1>
  <main id="content" hx-get="/api/dashboard" hx-trigger="load" hx-swap="innerHTML"></main>
</body>
</html>"""


@app.route("/")
def index():
    return app.send_static_file("index.html")


@app.route("/cards")
def cards_page():
    return app.send_static_file("index.html")


@app.route("/cards/<slug>")
def card_detail_page(slug: str):
    return app.send_static_file("index.html")


@app.route("/opportunities")
def opportunities_page():
    return app.send_static_file("index.html")


@app.route("/soldcards")
def sold_cards_page():
    return app.send_static_file("index.html")


# ─── JSON API endpoints ───────────────────────────────────────────────────────

@app.route("/api/dashboard")
def api_dashboard():
    """Return dashboard KPI summary cards as HTML fragment."""
    from .config import load_config
    _, products = load_config(CONFIG_PATH)
    active = [p for p in products if p.status != "sold"]

    products_with_data = get_all_products_with_trend()
    data_by_slug = {p["slug"]: p for p in products_with_data}

    total_listings = len(active)
    portfolio_value = sum(p.own_price_idr or 0 for p in active)
    market_value = 0
    alerts_count = 0
    for product in active:
        info = data_by_slug.get(product.slug, {})
        global_avg = info.get("global_average_idr")
        if global_avg is not None:
            market_value += global_avg
        if info.get("alert_level") == "red":
            alerts_count += 1

    store = TraceStore(BASE_DIR / "data" / "price_history.sqlite3")
    latest_run_id = store.latest_run_id()
    latest_run = store.inspect_run(latest_run_id) if latest_run_id is not None else None
    html = dashboard_fragment(
        total_listings=total_listings,
        portfolio_value=portfolio_value,
        market_value=market_value,
        alerts_count=alerts_count,
        latest_run=latest_run,
    )
    return html, 200, {"Content-Type": "text/html"}


@app.route("/api/cards")
def api_cards():
    """Return My Cards page fragment: action buttons + AG Grid rows."""
    from .config import load_config
    _, products = load_config(CONFIG_PATH)
    products = [p for p in products if p.status != "sold"]
    products_with_data = get_all_products_with_trend()
    data_by_slug = {p['slug']: p for p in products_with_data}

    return cards_fragment(products, data_by_slug), 200, {"Content-Type": "text/html"}


@app.route("/api/cards/<slug>")
def api_card_detail(slug: str):
    """Return card detail page as HTML fragment."""
    from .config import load_config
    _, products = load_config(CONFIG_PATH)
    product = next((p for p in products if p.slug == slug), None)
    if product is None:
        return "<p>Card not found</p>", 404, {"Content-Type": "text/html"}

    products_with_data = get_all_products_with_trend()
    info = next((p for p in products_with_data if p['slug'] == slug), {})
    observations = get_observations_for_slug(slug)
    chart_exists = (REPORTS_DIR / "charts" / f"{slug}.svg").exists()
    html = card_detail_fragment(
        product=product,
        info=info,
        observations=observations,
        chart_exists=chart_exists,
    )
    return html, 200, {"Content-Type": "text/html"}


@app.route("/api/soldcards")
def api_sold_cards():
    """Return sold cards grid as HTML fragment."""
    from .config import load_config
    _, products = load_config(CONFIG_PATH)
    sold = [p for p in products if p.status == "sold"]

    return sold_cards_fragment(sold), 200, {"Content-Type": "text/html"}


@app.route("/api/products/sync", methods=["POST"])
def api_sync_store_products():
    """Fetch store page, find products not in config, add them. Backfill added_at for existing active products."""
    from urllib.parse import quote, quote_plus

    from .card_parser import parse_card_identity
    from .config import load_config, save_config
    from .store_sync import get_active_store_product_urls_with_details

    settings, products = load_config(CONFIG_PATH)
    existing_urls = {p.tokopedia_url for p in products if p.tokopedia_url}
    today = utc_now().isoformat()

    store_products = get_active_store_product_urls_with_details(settings)
    new_products = [
        p for p in store_products
        if p.get("tokopedia_url") and p["tokopedia_url"] not in existing_urls
    ]

    added = []
    for item in new_products:
        identity = parse_card_identity(item["title"])
        term = identity.tokopedia_query() or item["title"]
        snkrdunk_term = identity.snkrdunk_query() or term
        sources = [
            Source(
                name="tokopedia competitors",
                kind="tokopedia_find",
                url=f"https://www.tokopedia.com/find/{term.replace(' ', '-').lower()}?ob=4",
            ),
            Source(
                name="ebay sold",
                kind="ebay_sold",
                url=f"https://www.ebay.com/sch/i.html?_nkw={quote_plus(term)}&LH_Sold=1&LH_Complete=1",
            ),
            Source(
                name="snkrdunk search",
                kind="snkrdunk_search",
                url=(
                    "https://snkrdunk.com/v3/search?func=all&refId=search"
                    f"&keyword={quote_plus(snkrdunk_term)}"
                    "&sortKey=default&cardVersion=2&categoryIds=6&perPage=30&page=1"
                ),
            ),
        ]
        product = Product(
            title=item["title"],
            own_price_idr=item["own_price_idr"],
            tokopedia_url=item["tokopedia_url"],
            search_terms=[term],
            sources=sources,
            status="active",
            added_at=today,
        )
        products.append(product)
        added.append(product.title)

    # Backfill added_at for existing active products that don't have it
    for i, product in enumerate(products):
        if product.status == "active" and not product.added_at:
            import dataclasses as dc
            products[i] = dc.replace(product, added_at=today)

    save_config(CONFIG_PATH, settings, products)
    return jsonify({"ok": True, "added_count": len(added), "added": added}), 201


@app.route("/api/opportunities")
def api_opportunities():
    """Return opportunities table as HTML fragment."""
    products_with_data = get_all_products_with_trend()
    return opportunities_fragment(products_with_data), 200, {"Content-Type": "text/html"}


# ─── Actions ─────────────────────────────────────────────────────────────────

@app.route("/api/cards/add", methods=["POST"])
def add_card():
    """Add a new card from Tokopedia URL and search keyword."""
    from .config import load_config, save_config
    from .card_parser import parse_card_identity

    data = request.get_json()
    tokopedia_url = data.get("tokopedia_url", "").strip()
    search_keyword = data.get("search_keyword", "").strip()

    if not tokopedia_url:
        return jsonify({"ok": False, "error": "Tokopedia URL is required"}), 400

    if search_keyword:
        if len(search_keyword) > 200:
            return jsonify({"ok": False, "error": "Search keyword too long (max 200 characters)"}), 400
        if not re.match(r"^[\w\s\-.,']+$", search_keyword, re.UNICODE):
            return jsonify({"ok": False, "error": "Search keyword contains invalid characters"}), 400

    settings, products = load_config(CONFIG_PATH)

    # Check if already exists
    for p in products:
        if p.tokopedia_url == tokopedia_url:
            return jsonify({"ok": False, "error": "Card already exists", "slug": p.slug}), 409

    # Build a placeholder title from search keyword for now
    title = search_keyword if search_keyword else tokopedia_url.split("/")[-1].split("?")[0].replace("-", " ")
    identity = parse_card_identity(title)

    product = Product(
        title=title,
        own_price_idr=0,
        tokopedia_url=tokopedia_url,
        search_terms=[search_keyword] if search_keyword else [],
        sources=[],
        status="active",
        sold_at="",
        added_at="",
    )

    products.append(product)
    save_config(CONFIG_PATH, settings, products)

    return jsonify({"ok": True, "slug": product.slug}), 201


@app.route("/api/cards/<slug>/search-term", methods=["PUT"])
def update_search_term(slug: str):
    """Update the search keyword for a card."""
    from .config import load_config, save_config

    data = request.get_json()
    search_term = data.get("search_term", "").strip()

    if not search_term:
        return jsonify({"ok": False, "error": "Search term cannot be empty"}), 400
    if len(search_term) > 200:
        return jsonify({"ok": False, "error": "Search term too long (max 200 characters)"}), 400
    if not re.match(r"^[\w\s\-.,']+$", search_term, re.UNICODE):
        return jsonify({"ok": False, "error": "Search term contains invalid characters"}), 400

    settings, products = load_config(CONFIG_PATH)
    product = next((p for p in products if p.slug == slug), None)
    if product is None:
        return jsonify({"ok": False, "error": "Card not found"}), 404

    # Update search_terms
    import dataclasses as dc
    updated = dc.replace(product, search_terms=[search_term] if search_term else [])
    products = [updated if p.slug == slug else p for p in products]
    save_config(CONFIG_PATH, settings, products)

    return jsonify({"ok": True}), 200


@app.route("/api/cards/<slug>/revert-sold", methods=["PUT"])
def revert_sold_card(slug: str):
    """Revert a sold card back to active status (user confirmed it still exists on store)."""
    from .config import load_config, save_config

    settings, products = load_config(CONFIG_PATH)
    product = next((p for p in products if p.slug == slug), None)
    if product is None:
        return jsonify({"ok": False, "error": "Card not found"}), 404
    if product.status != "sold":
        return jsonify({"ok": False, "error": "Card is not sold"}), 400

    import dataclasses as dc
    reverted = dc.replace(product, status="active", sold_at="")
    products = [reverted if p.slug == slug else p for p in products]
    save_config(CONFIG_PATH, settings, products)

    return jsonify({"ok": True, "title": product.title})


@app.route("/api/cards/<slug>/update-price", methods=["PUT"])
def update_card_price(slug: str):
    """Fetch the current Tokopedia listing price for this card and update own_price_idr."""
    from .config import load_config, save_config
    from .http import fetch_text
    from .infrastructure.parsing import parse_price_to_idr
    import re

    settings, products = load_config(CONFIG_PATH)
    product = next((p for p in products if p.slug == slug), None)
    if product is None:
        return jsonify({"ok": False, "error": "Card not found"}), 404

    tokopedia_url = product.tokopedia_url
    if not tokopedia_url:
        return jsonify({"ok": False, "error": "No Tokopedia URL configured for this card"}), 400

    try:
        html_text = fetch_text(tokopedia_url, timeout=15)
    except Exception as exc:
        return jsonify({"ok": False, "error": f"Failed to fetch Tokopedia page: {exc}"}), 502

    # Try to extract price from SSR structure first
    price_idr = None
    m = re.search(r'data-testid="price["\s>][^<>]*?Rp\s?([\d.]+)', html_text, re.I)
    if not m:
        m = re.search(r'"text_idr"\s*:\s*"Rp([\d.]+)"', html_text)
    if not m:
        m = re.search(r'Rp\s?([\d]{1,3}(?:,\d{3})*(?:\.\d+)?)', html_text)
    if m:
        price_idr = parse_price_to_idr(m.group(0))

    # Fallback: scan all Rp price candidates if no structured match found
    if not price_idr or price_idr < 10_000:
        price_candidates = re.findall(r'Rp\s?[\d.]+', html_text)
        for candidate in price_candidates:
            candidate_price = parse_price_to_idr(candidate)
            if candidate_price and candidate_price >= 10_000:
                price_idr = candidate_price
                break

    if not price_idr or price_idr < 10_000:
        return jsonify({"ok": False, "error": "Could not extract price from Tokopedia listing"}), 422

    # Update own_price_idr
    import dataclasses as dc
    updated = dc.replace(product, own_price_idr=price_idr)
    products = [updated if p.slug == slug else p for p in products]
    save_config(CONFIG_PATH, settings, products)

    from .reports import idr
    return jsonify({"ok": True, "own_price_idr": price_idr, "price_display": idr(price_idr)})


_refreshing_slugs = set()

def _run_refresh_bg(slug: str):
    """Background job that crawls tokopedia from search keyword and saves results."""
    global _refreshing_slugs
    try:
        from .config import load_config
        from .models import Product, Source
        from .scrapers import MarketplaceScraper

        _, products = load_config(CONFIG_PATH)
        product = next((p for p in products if p.slug == slug), None)
        if product is None:
            return

        # Build tokopedia source from search keyword
        keyword = product.search_terms[0] if product.search_terms else slug.replace("-", " ")
        tokopedia_url = f"https://www.tokopedia.com/find/{keyword.replace(' ', '-')}"
        tokopedia_source = Source(
            name="tokopedia competitors",
            kind="tokopedia_find",
            url=tokopedia_url,
        )

        settings = {"tokopedia_scam_floor_ratio": 0, "tokopedia_min_legit_results": 0}
        scraper = MarketplaceScraper(settings)
        run_at = utc_now()
        source_results = [scraper.scrape(tokopedia_source)]

        # Build a minimal product with just the tokopedia source for analysis
        analysis_product = Product(
            title=product.title,
            own_price_idr=product.own_price_idr,
            tokopedia_url=product.tokopedia_url,
            search_terms=product.search_terms,
            sources=[tokopedia_source],
        )
        from .ai import attach_ai_summaries
        from .analyze import analyze_product
        from .history import save_run
        from .reports import write_reports

        analyses = [analyze_product(analysis_product, source_results, run_at, settings)]
        analyses, ai_warnings = attach_ai_summaries(analyses)
        from .infrastructure.reports import write_reports
        save_run(analyses)
        run_id = int(analyses[0].run_at.timestamp())
        write_reports(analyses, run_id)
    finally:
        _refreshing_slugs.discard(slug)


@app.route("/run/<slug>", methods=["POST"])
def run_single_card(slug: str):
    global _refreshing_slugs
    if slug in _refreshing_slugs:
        return jsonify({"ok": False, "error": "Already refreshing"}), 409
    _refreshing_slugs.add(slug)
    thread = threading.Thread(target=_run_refresh_bg, args=(slug,), daemon=True)
    thread.start()
    return jsonify({"ok": True, "message": "Refresh started"}), 202


@app.route("/run/<slug>/status")
def run_single_card_status(slug: str):
    global _refreshing_slugs
    if slug in _refreshing_slugs:
        return jsonify({"state": "running"}), 200
    return jsonify({"state": "done"}), 200


@app.route("/run", methods=["POST"])
def run_scheduler():
    global _scheduler_pid, _scheduler_proc
    if _scheduler_pid is not None:
        return jsonify({"ok": False, "error": "Scheduler already running"}), 409
    try:
        log_path = BASE_DIR / "data" / "scheduler.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_handle = log_path.open("a", encoding="utf-8")
        proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "pokemon_price_scheduler",
                "run",
                "--config",
                str(CONFIG_PATH),
                "--debug",
            ],
            stdout=log_handle,
            stderr=log_handle,
            cwd=str(BASE_DIR)
        )
        _scheduler_pid = proc.pid
        _scheduler_proc = proc
        thread = threading.Thread(target=_run_scheduler_bg, args=(proc, log_handle), daemon=True)
        thread.start()
        return jsonify({"ok": True, "message": "Scheduler started"}), 202
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.route("/run/status")
def run_status():
    """SSE stream for scheduler progress."""
    def generate():
        global _scheduler_pid
        while True:
            if _scheduler_pid is None:
                yield "data: done\n\n"
                break
            try:
                os.kill(_scheduler_pid, 0)
                yield "data: running\n\n"
            except (ProcessLookupError, OSError):
                _scheduler_pid = None
                yield "data: done\n\n"
                break
            time.sleep(3)

    return Response(generate(), mimetype='text/event-stream')


@app.route("/api/runs/latest")
def api_latest_run():
    store = TraceStore(BASE_DIR / "data" / "price_history.sqlite3")
    run_id = store.latest_run_id()
    if run_id is None:
        return jsonify({"ok": False, "error": "No runs found"}), 404
    return jsonify({"ok": True, "run": store.inspect_run(run_id)})


@app.route("/latest.md")
def latest_md():
    return Response((REPORTS_DIR / "latest.md").read_text(), mimetype="text/plain")


@app.route("/latest.csv")
def latest_csv():
    return Response((REPORTS_DIR / "latest.csv").read_text(), mimetype="text/csv")


@app.route("/charts/<slug>.svg")
def chart_svg(slug: str):
    chart_path = REPORTS_DIR / "charts" / f"{slug}.svg"
    if not chart_path.exists():
        return "Chart not found", 404
    return Response(chart_path.read_text(), mimetype="image/svg+xml")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=False)
