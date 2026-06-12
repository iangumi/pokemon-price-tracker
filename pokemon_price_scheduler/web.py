from __future__ import annotations

import os
import html
import json
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse
import urllib.error
import urllib.request

from flask import Flask, Response, jsonify, request

from .history import (
    ai_repricing_advice_for_hash,
    counterpart_candidates_for_slug,
    get_all_products_with_trend,
    get_observations_for_slug,
    latest_ai_repricing_advice,
    price_history_for_slug,
    price_trend_for_slug,
    record_price_snapshot,
    repricing_queue,
    save_ai_repricing_advice,
    save_counterpart_candidates,
    suggested_prices,
)
from .http import fetch_text
from .inventory import (
    ConvertOpportunityInput,
    OpportunityInput,
    SaleInput,
    create_restock_listing,
    convert_opportunity,
    create_opportunity,
    get_opportunity,
    income_summary,
    inventory_rows,
    list_opportunities,
    mark_product_sold,
    parse_idr,
    sold_card_rows,
    sync_products as sync_inventory_products,
    update_sale_details,
)
from .models import Product, Source, utc_now
from .infrastructure.marketplace_sources import product_with_runtime_competitor_sources
from .infrastructure.counterparts import build_counterpart_candidates
from .infrastructure.parsing import clean_text, extract_json_objects, walk_json
from .reports import idr, pct
from .ui_components import (
    cards_fragment,
    card_detail_fragment,
    dashboard_fragment,
    inventory_fragment,
    opportunity_detail_fragment,
    opportunities_fragment,
    repricing_queue_fragment,
    reports_fragment,
    sold_cards_fragment,
)
from .v2.storage import TraceStore

BASE_DIR = Path(__file__).parent.parent
STATIC_DIR = BASE_DIR / "static"
REPORTS_DIR = BASE_DIR / "reports"
CARD_IMAGES_DIR = BASE_DIR / "data" / "card-images"
CONFIG_PATH = BASE_DIR / "config" / "products.json"

app = Flask(__name__, template_folder=str(REPORTS_DIR), static_folder=str(STATIC_DIR), static_url_path="")


# Track background scheduler process pid
_scheduler_pid = None
_scheduler_proc = None
_refreshing_slugs: set = set()


def _active_tokopedia_products(products: list[Product]) -> list[Product]:
    return [p for p in products if p.status != "sold" and bool(p.tokopedia_url)]


def _inventory_db_path() -> Path:
    if CONFIG_PATH.parent == BASE_DIR / "config":
        return BASE_DIR / "data" / "price_history.sqlite3"
    return CONFIG_PATH.parent / "inventory.sqlite3"


def _sync_inventory(settings: dict, products: list[Product]) -> None:
    sync_inventory_products(products, _inventory_db_path())


def _normalized_product_url(url: str) -> str:
    parsed = urlparse(url)
    path = parsed.path.rstrip("/")
    if not path:
        return ""
    host = parsed.netloc.lower()
    return f"{host}{path}" if host else path


def _dedupe_products_by_url(products: list[Product]) -> tuple[list[Product], int]:
    selected_by_url: dict[str, tuple[int, Product]] = {}
    passthrough: list[tuple[int, Product]] = []

    for index, product in enumerate(products):
        normalized = _normalized_product_url(product.tokopedia_url)
        if not normalized:
            passthrough.append((index, product))
            continue

        current = selected_by_url.get(normalized)
        if current is None:
            selected_by_url[normalized] = (index, product)
            continue

        _, current_product = current
        current_active = current_product.status != "sold"
        incoming_active = product.status != "sold"
        if incoming_active and not current_active:
            selected_by_url[normalized] = (index, product)
        elif incoming_active == current_active:
            selected_by_url[normalized] = (index, product)

    kept = passthrough + list(selected_by_url.values())
    kept.sort(key=lambda item: item[0])
    deduped = [product for _, product in kept]
    return deduped, len(products) - len(deduped)


def _extract_listing_title(html_text: str) -> str:
    patterns = (
        r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\'](?P<title>[^"\']+)',
        r'<meta[^>]+name=["\']title["\'][^>]+content=["\'](?P<title>[^"\']+)',
        r"<title>(?P<title>.*?)</title>",
    )
    for pattern in patterns:
        match = re.search(pattern, html_text, re.I | re.S)
        if not match:
            continue
        title = html.unescape(match.group("title"))
        title = re.sub(r"\s*\|\s*Tokopedia\b.*$", "", title, flags=re.I)
        title = clean_text(title)
        if title:
            return title
    return ""


def _extract_tokopedia_price(html_text: str) -> int | None:
    from .infrastructure.parsing import parse_price_to_idr

    patterns = (
        r'data-testid="price["\s>][^<>]*?Rp\s?([\d.]+)',
        r'"text_idr"\s*:\s*"Rp([\d.]+)"',
        r'"displayPrice"\s*:\s*"Rp([\d.]+)"',
        r'"priceAmount"\s*:\s*"Rp([\d.]+)"',
        r'Rp\s?([\d]{1,3}(?:,\d{3})*(?:\.\d+)?)',
    )
    for pattern in patterns:
        match = re.search(pattern, html_text, re.I)
        if match:
            price = parse_price_to_idr(match.group(0))
            if price and price >= 10_000:
                return price

    for candidate in re.findall(r'Rp\s?[\d.]+', html_text):
        price = parse_price_to_idr(candidate)
        if price and price >= 10_000:
            return price

    for obj in extract_json_objects(html_text):
        for node in walk_json(obj):
            if not isinstance(node, dict):
                continue
            for key in ("text_idr", "displayPrice", "priceAmount", "price", "minPrice"):
                value = node.get(key)
                if isinstance(value, str):
                    price = parse_price_to_idr(value)
                    if price and price >= 10_000:
                        return price
                elif isinstance(value, dict):
                    for nested_key in ("text_idr", "text", "price", "priceAmount"):
                        nested_value = value.get(nested_key)
                        if isinstance(nested_value, str):
                            price = parse_price_to_idr(nested_value)
                            if price and price >= 10_000:
                                return price
    return None


def _card_image_paths(slug: str) -> tuple[Path, Path]:
    return CARD_IMAGES_DIR / f"{slug}.bin", CARD_IMAGES_DIR / f"{slug}.json"


def _extract_tokopedia_image_url(html_text: str, base_url: str = "") -> str:
    patterns = (
        r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\'](?P<url>[^"\']+)',
        r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\'](?P<url>[^"\']+)',
        r'"og:image"\s*:\s*"(?P<url>[^"]+)',
        r'"imageUrl"\s*:\s*"(?P<url>[^"]+)',
        r'"mainImage"\s*:\s*"(?P<url>[^"]+)',
        r'"thumbnail"\s*:\s*"(?P<url>[^"]+)',
    )
    for pattern in patterns:
        match = re.search(pattern, html_text, re.I)
        if match:
            image_url = html.unescape(match.group("url"))
            if image_url:
                return urljoin(base_url, image_url)

    for obj in extract_json_objects(html_text):
        for node in walk_json(obj):
            if not isinstance(node, dict):
                continue
            for key in ("og:image", "imageUrl", "mainImage", "thumbnail", "image", "picture"):
                value = node.get(key)
                if isinstance(value, str) and value.strip():
                    return urljoin(base_url, html.unescape(value.strip()))
                if isinstance(value, dict):
                    for nested_key in ("url", "src", "imageUrl", "thumbnail"):
                        nested_value = value.get(nested_key)
                        if isinstance(nested_value, str) and nested_value.strip():
                            return urljoin(base_url, html.unescape(nested_value.strip()))
                if isinstance(value, list):
                    for item in value:
                        if isinstance(item, str) and item.strip():
                            return urljoin(base_url, html.unescape(item.strip()))
                        if isinstance(item, dict):
                            for nested_key in ("url", "src", "imageUrl", "thumbnail"):
                                nested_value = item.get(nested_key)
                                if isinstance(nested_value, str) and nested_value.strip():
                                    return urljoin(base_url, html.unescape(nested_value.strip()))
    return ""


def _download_binary(url: str, timeout: int = 15) -> tuple[bytes, str]:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
            "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            content_type = response.headers.get_content_type() or "application/octet-stream"
            return response.read(), content_type
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError(f"Could not fetch binary asset {url}: {exc}") from exc


def _cache_tokopedia_image(slug: str, listing_url: str, html_text: str) -> str:
    image_path, meta_path = _card_image_paths(slug)
    if image_path.exists() and meta_path.exists():
        return f"/card-images/{slug}"

    image_url = _extract_tokopedia_image_url(html_text, listing_url)
    if not image_url:
        return ""
    try:
        data, content_type = _download_binary(image_url)
    except Exception:
        return ""

    CARD_IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    image_path.write_bytes(data)
    meta_path.write_text(
        json.dumps(
            {
                "image_url": image_url,
                "listing_url": listing_url,
                "content_type": content_type,
                "fetched_at": utc_now().isoformat(),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return f"/card-images/{slug}"


def _ensure_card_image(product: Product) -> str:
    image_path, meta_path = _card_image_paths(product.slug)
    if image_path.exists() and meta_path.exists():
        return f"/card-images/{product.slug}"
    if not product.tokopedia_url:
        return ""
    try:
        page_text = fetch_text(product.tokopedia_url, timeout=15)
    except Exception:
        return ""
    return _cache_tokopedia_image(product.slug, product.tokopedia_url, page_text)


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


@app.route("/opportunities/<slug>")
def opportunity_detail_page(slug: str):
    return app.send_static_file("index.html")


@app.route("/inventory")
def inventory_page():
    return app.send_static_file("index.html")


@app.route("/repricing")
def repricing_page():
    return app.send_static_file("index.html")


@app.route("/reports")
def reports_page():
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
    products, _ = _dedupe_products_by_url(products)
    active = _active_tokopedia_products(products)

    products_with_data = get_all_products_with_trend()
    data_by_slug = {p["slug"]: p for p in products_with_data}

    total_listings = len(active)
    portfolio_value = sum(p.own_price_idr or 0 for p in active)
    market_value = 0
    alerts_count = 0
    active_card_rows = []
    for product in active:
        info = data_by_slug.get(product.slug, {})
        global_avg = info.get("global_average_idr")
        if global_avg is not None:
            market_value += global_avg
        if info.get("alert_level") == "red":
            alerts_count += 1
        active_card_rows.append(
            {
                "title": product.title,
                "slug": product.slug,
                "own_price": product.own_price_idr,
                "market_avg": global_avg,
                "delta": info.get("price_delta_percent"),
                "alert": info.get("alert_level", "none"),
                "alert_label": info.get("alert_label", ""),
            }
        )
    active_card_rows.sort(key=lambda row: row.get("own_price") or 0, reverse=True)

    store = TraceStore(BASE_DIR / "data" / "price_history.sqlite3")
    latest_run_id = store.latest_run_id()
    latest_run = store.inspect_run(latest_run_id) if latest_run_id is not None else None
    active_slugs = {p.slug for p in active}
    html = dashboard_fragment(
        total_listings=total_listings,
        portfolio_value=portfolio_value,
        market_value=market_value,
        alerts_count=alerts_count,
        latest_run=latest_run,
        active_cards=active_card_rows,
        repricing_rows=repricing_queue(active_slugs),
    )
    return html, 200, {"Content-Type": "text/html"}


@app.route("/api/reports")
def api_reports():
    """Return Reports page fragment with report links and source health."""
    store = TraceStore(BASE_DIR / "data" / "price_history.sqlite3")
    latest_run_id = store.latest_run_id()
    latest_run = store.inspect_run(latest_run_id) if latest_run_id is not None else None
    return reports_fragment(latest_run), 200, {"Content-Type": "text/html"}


@app.route("/api/cards")
def api_cards():
    """Return My Cards page fragment: action buttons + AG Grid rows."""
    from .config import load_config
    _, products = load_config(CONFIG_PATH)
    products, _ = _dedupe_products_by_url(products)
    products = _active_tokopedia_products(products)
    products_with_data = get_all_products_with_trend()
    data_by_slug = {p['slug']: p for p in products_with_data}

    return cards_fragment(products, data_by_slug), 200, {"Content-Type": "text/html"}


@app.route("/api/cards/<slug>")
def api_card_detail(slug: str):
    """Return card detail page as HTML fragment."""
    from .config import load_config
    _, products = load_config(CONFIG_PATH)
    products, _ = _dedupe_products_by_url(products)
    product = next((p for p in products if p.slug == slug), None)
    if product is None:
        return "<p>Card not found</p>", 404, {"Content-Type": "text/html"}

    products_with_data = get_all_products_with_trend()
    info = next((p for p in products_with_data if p['slug'] == slug), {})
    observations = get_observations_for_slug(slug)
    price_history = price_history_for_slug(slug)
    latest_snapshot = price_history[0] if price_history else {}
    market_avg = latest_snapshot.get("market_avg_price", info.get("global_average_idr"))
    image_url = _ensure_card_image(product)
    chart_exists = (REPORTS_DIR / "charts" / f"{slug}.svg").exists()
    html = card_detail_fragment(
        product=product,
        info=info,
        observations=observations,
        chart_exists=chart_exists,
        image_url=image_url,
        price_history=price_history,
        trend_7d=price_trend_for_slug(slug, 7),
        trend_30d=price_trend_for_slug(slug, 30),
        suggested=suggested_prices(market_avg),
        ai_advice=latest_ai_repricing_advice(slug) or {},
        counterparts=counterpart_candidates_for_slug(slug),
    )
    return html, 200, {"Content-Type": "text/html"}


def _card_evidence(slug: str):
    from .config import load_config
    _, products = load_config(CONFIG_PATH)
    products, _ = _dedupe_products_by_url(products)
    product = next((p for p in products if p.slug == slug), None)
    if product is None:
        return None
    products_with_data = get_all_products_with_trend()
    info = next((p for p in products_with_data if p['slug'] == slug), {})
    observations = get_observations_for_slug(slug)
    price_history = price_history_for_slug(slug)
    latest_snapshot = price_history[0] if price_history else {}
    market_avg = latest_snapshot.get("market_avg_price", info.get("global_average_idr"))
    return {
        "product": product,
        "info": info,
        "observations": observations,
        "price_history": price_history,
        "trend_7d": price_trend_for_slug(slug, 7),
        "trend_30d": price_trend_for_slug(slug, 30),
        "suggested": suggested_prices(market_avg),
        "counterparts": counterpart_candidates_for_slug(slug),
    }


@app.route("/api/cards/<slug>/counterparts")
def api_card_counterparts(slug: str):
    return jsonify({"ok": True, "counterparts": counterpart_candidates_for_slug(slug)})


@app.route("/api/cards/<slug>/counterparts/refresh", methods=["POST"])
def api_refresh_counterparts(slug: str):
    evidence = _card_evidence(slug)
    if evidence is None:
        return jsonify({"ok": False, "error": "Card not found"}), 404
    candidates = build_counterpart_candidates(evidence["product"], evidence["observations"])
    save_counterpart_candidates(slug, candidates)
    return jsonify({"ok": True, "counterparts": counterpart_candidates_for_slug(slug)})


@app.route("/api/cards/<slug>/ai-repricing-advice", methods=["POST"])
def api_ai_repricing_advice(slug: str):
    evidence = _card_evidence(slug)
    if evidence is None:
        return jsonify({"ok": False, "error": "Card not found"}), 404
    from .ai import MiniMaxClient, build_repricing_advice_payload, generate_repricing_advice, repricing_advice_input_hash

    payload = build_repricing_advice_payload(**evidence)
    input_hash = repricing_advice_input_hash(payload)
    body = request.get_json(silent=True) or {}
    force = request.args.get("force", "").lower() in {"1", "true", "yes"} or bool(body.get("force"))
    cached = None if force else ai_repricing_advice_for_hash(slug, input_hash)
    if cached:
        return jsonify({"ok": True, "cached": True, "record": cached})
    client = MiniMaxClient()
    try:
        advice = generate_repricing_advice(payload, client)
    except RuntimeError as exc:
        record = save_ai_repricing_advice(
            slug=slug,
            input_hash=input_hash,
            model=client.model,
            status="error",
            error=str(exc),
        )
        return jsonify({"ok": False, "error": str(exc), "record": record}), 400
    record = save_ai_repricing_advice(
        slug=slug,
        input_hash=input_hash,
        model=client.model,
        advice=advice,
        status="ok",
    )
    return jsonify({"ok": True, "cached": False, "record": record})


@app.route("/api/soldcards")
def api_sold_cards():
    """Return sold cards grid as HTML fragment."""
    from .config import load_config
    settings, products = load_config(CONFIG_PATH)
    products, _ = _dedupe_products_by_url(products)
    _sync_inventory(settings, products)
    sold = sold_card_rows(_inventory_db_path())

    return sold_cards_fragment(sold, income_summary(_inventory_db_path())), 200, {"Content-Type": "text/html"}


@app.route("/api/products/sync", methods=["POST"])
def api_sync_store_products():
    """Reconcile config products with the active Tokopedia store listing."""
    from urllib.parse import quote, quote_plus

    from .card_parser import parse_card_identity
    from .config import load_config, save_config
    from .store_sync import get_active_store_product_urls_with_details

    settings, products = load_config(CONFIG_PATH)
    today = utc_now().isoformat()
    products, deduped_count = _dedupe_products_by_url(products)

    store_products = get_active_store_product_urls_with_details(settings)
    store_by_url = {
        normalized: item
        for item in store_products
        if item.get("tokopedia_url")
        for normalized in [_normalized_product_url(str(item.get("tokopedia_url", "")))]
        if normalized
    }
    existing_by_url = {
        normalized: product
        for product in products
        if product.tokopedia_url
        for normalized in [_normalized_product_url(product.tokopedia_url)]
        if normalized
    }

    added = []
    updated_count = 0
    repaired_count = 0
    sold_count = 0
    updated_products = []

    import dataclasses as dc

    for product in products:
        normalized = _normalized_product_url(product.tokopedia_url)
        store_item = store_by_url.get(normalized)
        updated_product = product
        if product.status == "active" and not product.added_at:
            updated_product = dc.replace(updated_product, added_at=today)
        if product.status == "active" and normalized and store_item is not None:
            store_price = int(store_item.get("own_price_idr") or 0)
            if store_price > 0 and store_price != product.own_price_idr:
                if product.own_price_idr == 20_000_000:
                    repaired_count += 1
                updated_product = dc.replace(updated_product, own_price_idr=store_price)
                updated_count += 1
        elif product.status == "active" and normalized and store_by_url and normalized not in store_by_url:
            updated_product = dc.replace(updated_product, status="sold", sold_at=today)
            sold_count += 1
        updated_products.append(updated_product)
    products = updated_products

    for normalized, item in store_by_url.items():
        if normalized in existing_by_url:
            continue
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

    save_config(CONFIG_PATH, settings, products)
    _sync_inventory(settings, products)
    return jsonify({
        "ok": True,
        "added_count": len(added),
        "updated_count": updated_count,
        "repaired_count": repaired_count,
        "sold_count": sold_count,
        "deduped_count": deduped_count,
        "added": added,
    }), 201


@app.route("/api/opportunities")
def api_opportunities():
    """Return persistent buy-list opportunities as HTML fragment."""
    return opportunities_fragment(list_opportunities(_inventory_db_path())), 200, {"Content-Type": "text/html"}


@app.route("/api/opportunities", methods=["POST"])
def api_create_opportunity():
    data = request.get_json() or {}
    card_name = clean_text(str(data.get("card_name", "")))
    card_rarity = clean_text(str(data.get("card_rarity", ""))).upper()
    card_language = clean_text(str(data.get("card_language", "")))
    source = clean_text(str(data.get("source", "")))
    link = str(data.get("link", "")).strip()
    price = parse_idr(data.get("price_idr", data.get("price")))

    if not card_name:
        return jsonify({"ok": False, "error": "Card name is required"}), 400
    if not card_rarity:
        return jsonify({"ok": False, "error": "Card rarity is required"}), 400
    if not card_language:
        return jsonify({"ok": False, "error": "Card language is required"}), 400
    if not source:
        return jsonify({"ok": False, "error": "Source is required"}), 400
    if not link:
        return jsonify({"ok": False, "error": "Link is required"}), 400
    if price is None:
        return jsonify({"ok": False, "error": "Price is required"}), 400

    opportunity = create_opportunity(
        OpportunityInput(
            card_name=card_name,
            card_rarity=card_rarity,
            card_language=card_language,
            source=source,
            link=link,
            price_idr=price,
        ),
        _inventory_db_path(),
    )
    return jsonify({"ok": True, "slug": opportunity["slug"], "opportunity": opportunity}), 201


@app.route("/api/opportunities/<slug>")
def api_opportunity_detail(slug: str):
    opportunity = get_opportunity(slug, _inventory_db_path())
    if opportunity is None:
        return "<p>Opportunity not found</p>", 404, {"Content-Type": "text/html"}
    return opportunity_detail_fragment(opportunity), 200, {"Content-Type": "text/html"}


@app.route("/api/opportunities/<slug>/convert", methods=["POST"])
def api_convert_opportunity(slug: str):
    from urllib.parse import quote_plus
    from .card_parser import parse_card_identity
    from .config import load_config, save_config

    data = request.get_json() or {}
    bought_price = parse_idr(data.get("bought_at_price_idr", data.get("bought_at_price")))
    tokopedia_url = str(data.get("tokopedia_url", "")).strip()
    listing_price = parse_idr(data.get("listing_price_idr", data.get("listing_price")))
    if bought_price is None:
        return jsonify({"ok": False, "error": "Bought price is required"}), 400
    if tokopedia_url and listing_price is None:
        return jsonify({"ok": False, "error": "Listing price is required when Tokopedia URL is provided"}), 400
    if listing_price is not None and not tokopedia_url:
        return jsonify({"ok": False, "error": "Tokopedia URL is required when listing price is provided"}), 400

    opportunity = get_opportunity(slug, _inventory_db_path())
    if opportunity is None:
        return jsonify({"ok": False, "error": "Opportunity not found"}), 404
    if opportunity.get("status") == "converted":
        return jsonify({"ok": False, "error": "Opportunity is already converted"}), 400

    product = None
    created_listing = False
    if tokopedia_url and listing_price is not None:
        settings, products = load_config(CONFIG_PATH)
        normalized = _normalized_product_url(tokopedia_url)
        if any(_normalized_product_url(p.tokopedia_url) == normalized for p in products if p.tokopedia_url):
            return jsonify({"ok": False, "error": "Tokopedia listing already exists"}), 409
        title = opportunity["title"]
        identity = parse_card_identity(title)
        term = identity.tokopedia_query() or title
        snkrdunk_term = identity.snkrdunk_query() or term
        product = Product(
            title=title,
            own_price_idr=listing_price,
            tokopedia_url=tokopedia_url,
            search_terms=[term],
            sources=[
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
            ],
            status="active",
            added_at=utc_now().isoformat(),
        )
        products.append(product)
        save_config(CONFIG_PATH, settings, products)
        created_listing = True

    converted = convert_opportunity(
        slug,
        ConvertOpportunityInput(
            bought_at_price_idr=bought_price,
            tokopedia_url=tokopedia_url,
            listing_price_idr=listing_price,
        ),
        product=product,
        path=_inventory_db_path(),
    )
    if converted is None:
        return jsonify({"ok": False, "error": "Opportunity not found"}), 404

    return jsonify({"ok": True, "slug": slug, "created_listing": created_listing, "opportunity": converted})


@app.route("/api/inventory")
def api_inventory():
    from .config import load_config
    settings, products = load_config(CONFIG_PATH)
    _sync_inventory(settings, products)
    return inventory_fragment(inventory_rows(_inventory_db_path())), 200, {"Content-Type": "text/html"}


@app.route("/api/repricing")
def api_repricing():
    """Return repricing queue table as HTML fragment."""
    from .config import load_config
    _, products = load_config(CONFIG_PATH)
    active_slugs = {p.slug for p in _active_tokopedia_products(products)}
    return repricing_queue_fragment(repricing_queue(active_slugs)), 200, {"Content-Type": "text/html"}


# ─── Actions ─────────────────────────────────────────────────────────────────

@app.route("/api/cards/add", methods=["POST"])
def add_card():
    """Add a new card from Tokopedia URL and search keyword."""
    from .config import load_config, save_config

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

    title = ""
    page_text = ""
    try:
        page_text = fetch_text(tokopedia_url, timeout=15)
        title = _extract_listing_title(page_text)
        price_idr = _extract_tokopedia_price(page_text)
    except Exception:
        title = ""
        price_idr = None
    if not title:
        title = search_keyword if search_keyword else tokopedia_url.split("/")[-1].split("?")[0].replace("-", " ")
    title = clean_text(title)

    product = Product(
        title=title,
        own_price_idr=price_idr or 0,
        tokopedia_url=tokopedia_url,
        search_terms=[search_keyword] if search_keyword else [],
        sources=[],
        status="active",
        sold_at="",
        added_at="",
    )

    products.append(product)
    save_config(CONFIG_PATH, settings, products)
    _sync_inventory(settings, products)

    if page_text:
        _cache_tokopedia_image(product.slug, tokopedia_url, page_text)
    if price_idr is not None:
        record_price_snapshot(
            card_id=product.slug,
            tokopedia_price=price_idr,
            created_at=utc_now().isoformat(),
            source_summary="initial add snapshot",
        )

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
    create_restock_listing(reverted, _inventory_db_path())

    return jsonify({"ok": True, "title": product.title})


@app.route("/api/cards/<slug>/mark-sold", methods=["POST"])
def mark_sold_card(slug: str):
    """Manually move an active card to sold and record sale income details."""
    from .config import load_config, save_config

    data = request.get_json() or {}
    sold_at = str(data.get("sold_at", "")).strip()
    sold_price = parse_idr(data.get("sold_price_idr", data.get("sold_price")))
    bought_at_price = parse_idr(data.get("bought_at_price_idr", data.get("bought_at_price")))
    net_income = parse_idr(data.get("net_income_idr"))

    if not re.match(r"^\d{4}-\d{2}-\d{2}", sold_at):
        return jsonify({"ok": False, "error": "Sold date is required"}), 400
    if sold_price is None:
        return jsonify({"ok": False, "error": "Sold price is required"}), 400
    if bought_at_price is None:
        return jsonify({"ok": False, "error": "Bought price is required"}), 400
    if net_income is None:
        return jsonify({"ok": False, "error": "Net income is required"}), 400

    settings, products = load_config(CONFIG_PATH)
    product = next((p for p in products if p.slug == slug), None)
    if product is None:
        return jsonify({"ok": False, "error": "Card not found"}), 404
    if product.status == "sold":
        return jsonify({"ok": False, "error": "Card is already sold"}), 400

    import dataclasses as dc
    sold_at_value = sold_at if "T" in sold_at else f"{sold_at}T00:00:00+00:00"
    sold_product = dc.replace(product, status="sold", sold_at=sold_at_value)
    products = [sold_product if p.slug == slug else p for p in products]
    save_config(CONFIG_PATH, settings, products)
    mark_product_sold(
        sold_product,
        SaleInput(
            sold_at=sold_at_value,
            sold_price_idr=sold_price,
            bought_at_price_idr=bought_at_price,
            net_income_idr=net_income,
        ),
        _inventory_db_path(),
    )

    return jsonify({"ok": True, "title": product.title, "slug": slug})


@app.route("/api/cards/<slug>/sale-details", methods=["POST"])
def update_sold_sale_details(slug: str):
    """Update income details for an existing sold card."""
    from .config import load_config, save_config

    data = request.get_json() or {}
    sold_at = str(data.get("sold_at", "")).strip()
    sold_price = parse_idr(data.get("sold_price_idr", data.get("sold_price")))
    bought_at_price = parse_idr(data.get("bought_at_price_idr", data.get("bought_at_price")))
    net_income = parse_idr(data.get("net_income_idr"))

    if not re.match(r"^\d{4}-\d{2}-\d{2}", sold_at):
        return jsonify({"ok": False, "error": "Sold date is required"}), 400
    if sold_price is None:
        return jsonify({"ok": False, "error": "Sold price is required"}), 400
    if bought_at_price is None:
        return jsonify({"ok": False, "error": "Bought price is required"}), 400
    if net_income is None:
        return jsonify({"ok": False, "error": "Net income is required"}), 400

    settings, products = load_config(CONFIG_PATH)
    product = next((p for p in products if p.slug == slug), None)
    if product is None:
        return jsonify({"ok": False, "error": "Card not found"}), 404

    import dataclasses as dc
    sold_at_value = sold_at if "T" in sold_at else f"{sold_at}T00:00:00+00:00"
    sold_product = dc.replace(product, status="sold", sold_at=sold_at_value)
    products = [sold_product if p.slug == slug else p for p in products]
    save_config(CONFIG_PATH, settings, products)
    update_sale_details(
        sold_product,
        SaleInput(
            sold_at=sold_at_value,
            sold_price_idr=sold_price,
            bought_at_price_idr=bought_at_price,
            net_income_idr=net_income,
        ),
        _inventory_db_path(),
    )

    return jsonify({"ok": True, "title": product.title, "slug": slug})


@app.route("/api/cards/<slug>/update-price", methods=["PUT"])
def update_card_price(slug: str):
    """Fetch the current Tokopedia listing price for this card and update own_price_idr."""
    from .config import load_config, save_config
    from .http import fetch_text

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

    price_idr = _extract_tokopedia_price(html_text)

    if not price_idr or price_idr < 10_000:
        return jsonify({"ok": False, "error": "Could not extract price from Tokopedia listing"}), 422

    # Update own_price_idr
    import dataclasses as dc
    updated = dc.replace(product, own_price_idr=price_idr)
    products = [updated if p.slug == slug else p for p in products]
    save_config(CONFIG_PATH, settings, products)
    _cache_tokopedia_image(slug, tokopedia_url, html_text)
    record_price_snapshot(
        card_id=slug,
        tokopedia_price=price_idr,
        created_at=utc_now().isoformat(),
        source_summary="manual sync",
    )

    from .reports import idr
    return jsonify({"ok": True, "own_price_idr": price_idr, "price_display": idr(price_idr)})


_refreshing_slugs = set()

def _run_refresh_bg(slug: str):
    """Background job that crawls tokopedia from search keyword and saves results."""
    global _refreshing_slugs
    try:
        from .config import load_config
        from .scrapers import MarketplaceScraper

        _, products = load_config(CONFIG_PATH)
        product = next((p for p in products if p.slug == slug), None)
        if product is None:
            return

        analysis_product = product_with_runtime_competitor_sources(product)

        settings = {"tokopedia_scam_floor_ratio": 0, "tokopedia_min_legit_results": 0}
        scraper = MarketplaceScraper(settings)
        run_at = utc_now()
        source_results = [scraper.scrape(source) for source in analysis_product.sources]
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


@app.route("/card-images/<slug>")
def card_image(slug: str):
    image_path, meta_path = _card_image_paths(slug)
    if not image_path.exists():
        return "Image not found", 404
    content_type = "image/jpeg"
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            content_type = str(meta.get("content_type") or content_type)
        except Exception:
            pass
    return Response(image_path.read_bytes(), mimetype=content_type)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=False)
