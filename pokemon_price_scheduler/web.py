from __future__ import annotations

import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

from flask import Flask, Response, jsonify, render_template_string, request

from .history import get_all_products_with_trend, get_observations_for_slug, history_for_slug
from .models import Product, Source, utc_now
from .reports import idr, pct

BASE_DIR = Path(__file__).parent.parent
STATIC_DIR = BASE_DIR / "static"
REPORTS_DIR = BASE_DIR / "reports"
CONFIG_PATH = BASE_DIR / "config" / "products.json"

app = Flask(__name__, template_folder=str(REPORTS_DIR), static_folder=str(STATIC_DIR), static_url_path="")


# Track background scheduler process pid
_scheduler_pid = None
_refreshing_slugs: set = set()


def _run_scheduler_bg():
    global _scheduler_pid
    import sys
    import traceback
    import logging
    try:
        proc = subprocess.Popen(
            [sys.executable, "-m", "pokemon_price_scheduler", "run", "--config", str(CONFIG_PATH)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            cwd=str(BASE_DIR),
        )
        proc.wait()
    except Exception:
        logging.error(f"Scheduler failed: {traceback.format_exc()}")
        sys.stderr.write(f"Scheduler error: {traceback.format_exc()}\n")
    finally:
        _scheduler_pid = None


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

    html = f"""<section class="dashboard-kpis">
  <div class="kpi-card">
    <span class="kpi-label">Total Active Listings</span>
    <strong class="kpi-value">{total_listings:,}</strong>
    <span class="kpi-hint">Live cards in your store</span>
  </div>
  <div class="kpi-card">
    <span class="kpi-label">Total Active Portfolio Value</span>
    <strong class="kpi-value">{idr(portfolio_value)}</strong>
    <span class="kpi-hint">Sum of your Tokopedia prices</span>
  </div>
  <div class="kpi-card">
    <span class="kpi-label">Total Market Value</span>
    <strong class="kpi-value">{idr(market_value)}</strong>
    <span class="kpi-hint">Sum of global averages (priced cards)</span>
  </div>
  <div class="kpi-card kpi-card--alert">
    <span class="kpi-label">Active Alerts</span>
    <strong class="kpi-value">{alerts_count:,}</strong>
    <span class="kpi-hint">Flagged as price too high</span>
  </div>
</section>"""
    return html, 200, {"Content-Type": "text/html"}


@app.route("/api/cards")
def api_cards():
    """Return My Cards page fragment: action buttons + DataTable rows."""
    from .config import load_config
    _, products = load_config(CONFIG_PATH)
    products = [p for p in products if p.status != "sold"]
    products_with_data = get_all_products_with_trend()
    data_by_slug = {p['slug']: p for p in products_with_data}

    rows = []
    for product in products:
        slug = product.slug
        info = data_by_slug.get(slug, {})
        own_price = product.own_price_idr
        global_avg = info.get("global_average_idr")
        alert = info.get("alert_level", "none")
        alert_label = info.get("alert_label", "")
        delta = info.get("price_delta_percent")

        own_price_str = f"Rp {own_price:,.0f}".replace(",", ".") if own_price else "-"
        global_str = f"Rp {global_avg:,.0f}".replace(",", ".") if global_avg else "-"
        delta_str = f"{delta:+.1f}%" if delta is not None else "-"
        own_order = own_price if own_price else ""
        global_order = global_avg if global_avg is not None else ""
        delta_order = delta if delta is not None else ""

        row_class = f' class="alert-{alert}"' if alert in ("red", "amber") else ""
        rows.append(f"""<tr{row_class}>
          <td><a href="/cards/{slug}">{product.title}</a></td>
          <td data-order="{own_order}">{own_price_str}</td>
          <td data-order="{global_order}">{global_str}</td>
          <td>{product.language or '-'}</td>
          <td data-order="{delta_order}">{delta_str}</td>
          <td class="alert-cell" data-alert="{alert_label}">{alert_label or '-'}</td>
        </tr>""")

    actions = """
    <div class="page-actions">
      <button class="btn" onclick="syncNewProducts()">+ Sync New Products</button>
      <button class="btn" onclick="openAddCardModal()">+ Add Card</button>
    </div>"""

    if not rows:
        table = "<p style='color:var(--muted);font-size:13px;padding:var(--sp-2) 0;'>No cards configured.</p>"
    else:
        table = f"""<table id="cards-table">
  <thead>
    <tr>
      <th>Card</th>
      <th>Your Price</th>
      <th>Global Avg</th>
      <th>Language</th>
      <th>Delta</th>
      <th>Alert</th>
    </tr>
  </thead>
  <tbody>{"".join(rows)}</tbody>
</table>"""

    html = actions + table
    return html, 200, {"Content-Type": "text/html"}


@app.route("/api/cards/<slug>")
def api_card_detail(slug: str):
    """Return card detail page as HTML fragment."""
    from .config import load_config
    from .history import history_for_slug
    from .reports import idr, pct
    _, products = load_config(CONFIG_PATH)
    product = next((p for p in products if p.slug == slug), None)
    if product is None:
        return "<p>Card not found</p>", 404, {"Content-Type": "text/html"}

    history = history_for_slug(slug)
    products_with_data = get_all_products_with_trend()
    info = next((p for p in products_with_data if p['slug'] == slug), {})

    identity = product.card_identity
    own_price = product.own_price_idr
    global_avg = info.get("global_average_idr")
    delta = info.get("price_delta_percent")
    alert = info.get("alert_level", "none")
    alert_label = info.get("alert_label", "")
    is_sold = product.status == "sold"

    badge = f'<span class="alert-badge {alert}">{alert_label}</span>' if alert != "none" else "-"
    metrics_html = f"""
    <section class="metrics">
      <div><span>Your Price</span><strong>{idr(own_price)}</strong></div>
      <div><span>Global Avg</span><strong>{idr(global_avg)}</strong></div>
      <div><span>Delta</span><strong>{pct(delta)}</strong></div>
      <div><span>Alert</span><strong>{badge}</strong></div>
    </section>"""

    if is_sold:
        sold_date = product.sold_at[:10] if product.sold_at else "-"
        metrics_html = f"""
    <section class="metrics">
      <div><span>Your Price</span><strong>{idr(own_price)}</strong></div>
      <div><span>Sold At</span><strong>{sold_date}</strong></div>
      <div><span>Status</span><strong style="color:var(--red)">SOLD</strong></div>
    </section>"""

    added_date = product.added_at[:10] if product.added_at else "-"
    sold_date = product.sold_at[:10] if product.sold_at else "-"
    identity_html = f"""
    <section class="identity">
      <h2>Card Identity</h2>
      <dl>
        <dt>Name</dt><dd>{identity.name or product.title}</dd>
        <dt>Set</dt><dd>{identity.set_symbol or '-'}</dd>
        <dt>Card Number</dt><dd>{identity.card_number or '-'}</dd>
        <dt>Rarity</dt><dd>{identity.rarity or '-'}</dd>
        <dt>Language</dt><dd>{identity.language or '-'}</dd>
        <dt>Condition</dt><dd>{identity.condition or '-'}</dd>
        <dt>Added</dt><dd>{added_date}</dd>
        <dt>Sold</dt><dd>{sold_date if is_sold else '-'}</dd>
      </dl>
    </section>"""

    chart_path = f"charts/{slug}.svg"
    chart_exists = (REPORTS_DIR / chart_path).exists()
    chart_html = f"""
    <section>
      <h2>Price Change</h2>
      <img src="/{chart_path}" alt="Price chart for {identity.name or product.title}">
    </section>""" if chart_exists else ""

    # Fetch latest observations from DB for display
    observations = get_observations_for_slug(slug)
    obs_by_source: dict[str, list[dict]] = {}
    for obs in observations:
        obs_by_source.setdefault(obs["source_name"], []).append(obs)

    # Build source sections from DB observations
    MY_STORE_MARKER = "(Our store) - "
    MY_STORE_PATTERNS = ("tokopedia.com/iantechcardstore", "tokopedia.com/iantechstore")
    source_sections = []
    if obs_by_source:
        for src_name, obs_list in obs_by_source.items():
            # Sort by price descending
            sorted_obs = sorted(obs_list, key=lambda o: o["price_idr"], reverse=True)
            rows = []
            for obs in sorted_obs[:10]:
                legit = "yes" if obs["is_legit"] else "filtered"
                is_own = any(p in obs["url"] for p in MY_STORE_MARKER if p)
                is_own = any(p in obs["url"] for p in MY_STORE_PATTERNS)
                title = obs["title"] or src_name
                if is_own:
                    title = f'<span style="color:var(--green);font-weight:600;">{MY_STORE_MARKER}{title}</span>'
                rows.append(
                    f"""<tr{' style="background:#4ade8018;"' if is_own else ''}>
                      <td><a href="{obs['url']}" target="_blank">{title}</a></td>
                      <td>Rp {obs['price_idr']:,}</td>
                      <td>{obs['source_kind']}</td>
                      <td>-</td>
                      <td>{legit}</td>
                    </tr>"""
                )
            source_sections.append(f"""
            <section>
              <h2>{src_name}</h2>
              <table>
                <thead><tr><th>Listing</th><th>Price</th><th>Source</th><th>Match</th><th>Used</th></tr></thead>
                <tbody>{''.join(rows)}</tbody>
              </table>
            </section>""")
    else:
        source_sections.append(
            """<section>
              <p style="color:var(--muted);font-size:12px;">No price data yet. Click "Refresh Prices" to search Tokopedia.</p>
            </section>"""
        )
    sources_html = "".join(source_sections)

    tokopedia_url = product.tokopedia_url or next(
        (s.url for s in product.sources if s.kind == "tokopedia_find"), ""
    )

    search_terms_display = product.search_terms[0] if product.search_terms else ""

    buttons_html = ""
    if not is_sold:
        buttons_html = f"""
    <div style="display:flex;justify-content:flex-end;gap:8px;margin-bottom:var(--sp-2)">
      <button class="btn" onclick="window.open('{tokopedia_url}', '_blank')">View Product on Tokopedia</button>
      <button id="refresh-btn" class="btn" onclick="refreshCard('{slug}')">
        <span id="refresh-btn-text">Refresh Competitor Prices</span>
      </button>
      <button id="update-price-btn" class="btn" onclick="updatePrice('{slug}')">
        <span id="update-price-btn-text">Sync Store Price</span>
      </button>
    </div>
    <div style="display:flex;gap:8px;margin-bottom:var(--sp-2);align-items:center;">
      <label style="font-size:11px;color:var(--muted);white-space:nowrap;">Search Keyword:</label>
      <input id="search-term-input" type="text" value="{search_terms_display}"
             style="flex:1;background:var(--surface-2);border:1px solid var(--border);border-radius:var(--radius-sm);color:var(--text);padding:6px 8px;font-size:12px;">
      <button class="btn" onclick="updateSearchTerm('{slug}')">Save</button>
    </div>"""
    else:
        buttons_html = f"""
    <div style="display:flex;justify-content:flex-end;gap:8px;margin-bottom:var(--sp-2)">
      <button class="btn" onclick="window.open('{tokopedia_url}', '_blank')">View Product on Tokopedia</button>
    </div>"""

    html = f"""
    {buttons_html}
    {metrics_html}
    {identity_html}
    {chart_html}
    {sources_html}"""

    return html, 200, {"Content-Type": "text/html"}


@app.route("/api/soldcards")
def api_sold_cards():
    """Return sold cards grid as HTML fragment."""
    from .config import load_config
    _, products = load_config(CONFIG_PATH)
    sold = [p for p in products if p.status == "sold"]

    cards = []
    for product in sold:
        sold_date = product.sold_at[:10] if product.sold_at else "-"
        own_price_str = idr(product.own_price_idr)
        cards.append(f"""
        <div class="card sold-card" id="sold-{product.slug}">
          <div class="card-top">
            <a href="/cards/{product.slug}" class="card-title" style="text-decoration:none;color:inherit;">{product.title}</a>
            <span class="alert-badge red">SOLD</span>
          </div>
          <div class="card-lang">{product.language}</div>
          <div class="card-prices">
            <div class="price-box">
              <span>Your Price</span>
              <strong>{own_price_str}</strong>
            </div>
            <div class="price-box">
              <span>Sold At</span>
              <strong>{sold_date}</strong>
            </div>
          </div>
          <div style="margin-top:var(--sp-1);">
            <button class="btn" onclick="revertSold('{product.slug}')">Still in store</button>
          </div>
        </div>""")

    html = f"""
    <div class="cards-grid">{"".join(cards) if cards else "<p>No sold cards yet.</p>"}</div>"""
    return html, 200, {"Content-Type": "text/html"}


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
                url=f"https://snkrdunk.com/v3/search?func=all&keyword={quote_plus(term)}&perPage=30&page=1",
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

    rows = []
    for p in products_with_data:
        rows.append(f"""
        <tr>
          <td><a href="/cards/{p['slug']}">{p.get('title', p['slug'])}</a></td>
          <td>-</td>
          <td>-</td>
          <td>-</td>
          <td>-</td>
          <td>-</td>
          <td>-</td>
          <td>Review as potential import if global listings are liquid and local listings are thin.</td>
        </tr>""")

    html = f"""<table>
      <thead><tr><th>Card</th><th>Set</th><th>Rarity</th><th>Global Avg</th><th>Global Items</th><th>Local Items</th><th>Score</th><th>Note</th></tr></thead>
      <tbody>{"".join(rows) if rows else "<tr><td colspan='8'>No opportunity candidates yet.</td></tr>"}</tbody>
    </table>"""
    return html, 200, {"Content-Type": "text/html"}


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
    global _scheduler_pid
    try:
        proc = subprocess.Popen(
            [sys.executable, "-m", "pokemon_price_scheduler", "run", "--config", str(CONFIG_PATH)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            cwd=str(BASE_DIR)
        )
        _scheduler_pid = proc.pid
        thread = threading.Thread(target=_run_scheduler_bg, daemon=True)
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