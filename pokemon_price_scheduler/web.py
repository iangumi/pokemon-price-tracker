from __future__ import annotations

import os
import subprocess
import threading
import time
from pathlib import Path

from flask import Flask, Response, jsonify, render_template_string, request

from .history import get_all_products_with_trend
from .models import Product, Source, utc_now

BASE_DIR = Path(__file__).parent.parent
STATIC_DIR = BASE_DIR / "static"
REPORTS_DIR = BASE_DIR / "reports"
CONFIG_PATH = BASE_DIR / "config" / "products.json"

app = Flask(__name__, template_folder=str(REPORTS_DIR), static_folder=str(STATIC_DIR), static_url_path="")

# Track background scheduler process pid
_scheduler_pid = None


def _run_scheduler_bg():
    global _scheduler_pid
    try:
        subprocess.run(
            ["python3", "-m", "pokemon_price_scheduler", "run", "--config", str(CONFIG_PATH)],
            capture_output=True, text=True, timeout=600, cwd=str(BASE_DIR)
        )
    except Exception:
        pass
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


# ─── JSON API endpoints ───────────────────────────────────────────────────────

@app.route("/api/dashboard")
def api_dashboard():
    """Return dashboard table rows as HTML fragment."""
    from .config import load_config
    _, products = load_config(CONFIG_PATH)

    products_with_data = get_all_products_with_trend()
    data_by_slug = {p['slug']: p for p in products_with_data}

    rows = []
    for product in products:
        slug = product.slug
        info = data_by_slug.get(slug, {})
        delta = info.get("price_delta_percent")
        alert = info.get("alert_level", "none")
        own_price = product.own_price_idr
        global_avg = info.get("global_average_idr")
        lang = product.language

        delta_str = f"{delta:+.1f}%" if delta is not None else "-"
        own_price_str = f"Rp {own_price:,.0f}".replace(",", ".") if own_price else "-"
        global_str = f"Rp {global_avg:,.0f}".replace(",", ".") if global_avg else "-"

        rows.append(f"""
        <tr class="alert-{alert}">
          <td><a href="/cards/{slug}">{product.title}</a></td>
          <td>{product.card_identity.set_symbol or '-'} </td>
          <td>{product.card_identity.rarity or '-'} </td>
          <td>{lang}</td>
          <td>{product.card_identity.condition or '-'} </td>
          <td>{own_price_str}</td>
          <td>{global_str}</td>
          <td>{delta_str}</td>
          <td>{alert}</td>
        </tr>""")

    html = f"""<table>
      <thead>
        <tr>
          <th>Card</th><th>Set</th><th>Rarity</th><th>Language</th><th>Condition</th>
          <th>Your Price</th><th>Global Avg</th><th>Delta</th><th>Alert</th>
        </tr>
      </thead>
      <tbody>{"".join(rows) if rows else "<tr><td colspan='9'>No data yet. Run the scheduler to fetch prices.</td></tr>"}</tbody>
    </table>"""
    return html, 200, {"Content-Type": "text/html"}


@app.route("/api/cards")
def api_cards():
    """Return cards grid as HTML fragment."""
    from .config import load_config
    _, products = load_config(CONFIG_PATH)
    products_with_data = get_all_products_with_trend()
    data_by_slug = {p['slug']: p for p in products_with_data}

    cards = []
    for product in products:
        slug = product.slug
        info = data_by_slug.get(slug, {})
        own_price = product.own_price_idr
        global_avg = info.get("global_average_idr")
        alert = info.get("alert_level", "none")
        own_trend = info.get("own_trend_percent")
        market_trend = info.get("market_trend_percent")

        own_price_str = f"Rp {own_price:,.0f}".replace(",", ".") if own_price else "-"
        global_str = f"Rp {global_avg:,.0f}".replace(",", ".") if global_avg else "-"
        own_trend_str = f"{own_trend:+.1f}%" if own_trend is not None else "-"
        market_trend_str = f"{market_trend:+.1f}%" if market_trend is not None else "-"

        cards.append(f"""
        <a href="/cards/{slug}" class="card">
          <div class="card-top">
            <div class="card-title">{product.title}</div>
            {"<span class='alert-badge " + alert + "'>" + alert + "</span>" if alert != "none" else ""}
          </div>
          <div class="card-lang">{product.language}</div>
          <div class="card-prices">
            <div class="price-box">
              <span>Your Price</span>
              <strong>{own_price_str}</strong>
              <div class="trend {'neutral' if own_trend is None else 'up' if own_trend > 0 else 'down' if own_trend < 0 else 'flat'}">{own_trend_str}</div>
            </div>
            <div class="price-box">
              <span>Market Avg</span>
              <strong>{global_str}</strong>
              <div class="trend {'neutral' if market_trend is None else 'up' if market_trend > 0 else 'down' if market_trend < 0 else 'flat'}">{market_trend_str}</div>
            </div>
          </div>
        </a>""")

    html = f"""
    <div style="display:flex;justify-content:flex-end;margin-bottom:var(--sp-2)">
      <button class="btn" onclick="openAddCardModal()">+ Add Card</button>
    </div>
    <div class="cards-grid">{"".join(cards) if cards else "<p>No cards configured.</p>"}</div>"""
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

    metrics_html = f"""
    <section class="metrics">
      <div><span>Your Price</span><strong>{idr(own_price)}</strong></div>
      <div><span>Global Avg</span><strong>{idr(global_avg)}</strong></div>
      <div><span>Delta</span><strong>{pct(delta)}</strong></div>
      <div><span>Alert</span><strong>{alert}</strong></div>
    </section>"""

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
      </dl>
    </section>"""

    chart_path = f"charts/{slug}.svg"
    chart_exists = (REPORTS_DIR / chart_path).exists()
    chart_html = f"""
    <section>
      <h2>Price Change</h2>
      <img src="/{chart_path}" alt="Price chart for {identity.name or product.title}">
    </section>""" if chart_exists else ""

    source_sections = []
    for src in product.sources:
        source_sections.append(f"""
        <section>
          <h2>{src.name}</h2>
          <p><a href="{src.url}" target="_blank">Open source search</a></p>
          <table>
            <thead><tr><th>Listing</th><th>Price</th><th>Source</th><th>Match</th><th>Used</th></tr></thead>
            <tbody><tr><td colspan="5">No comparable listings parsed.</td></tr></tbody>
          </table>
        </section>""")

    sources_html = "".join(source_sections)

    tokopedia_url = product.tokopedia_url or next(
        (s.url for s in product.sources if s.kind == "tokopedia_find"), ""
    )

    search_terms_display = product.search_terms[0] if product.search_terms else ""
    html = f"""
    <div style="display:flex;justify-content:flex-end;gap:8px;margin-bottom:var(--sp-2)">
      <button class="btn" onclick="window.open('{tokopedia_url}', '_blank')">Check Tokopedia Price</button>
      <button class="btn" onclick="refreshCard('{slug}')">Refresh Prices</button>
    </div>
    <div style="display:flex;gap:8px;margin-bottom:var(--sp-2);align-items:center;">
      <label style="font-size:11px;color:var(--muted);white-space:nowrap;">Search Keyword:</label>
      <input id="search-term-input" type="text" value="{search_terms_display}"
             style="flex:1;background:var(--surface-2);border:1px solid var(--border);border-radius:var(--radius-sm);color:var(--text);padding:6px 8px;font-size:12px;">
      <button class="btn" onclick="updateSearchTerm('{slug}')">Save</button>
    </div>
    {metrics_html}
    {identity_html}
    {chart_html}
    {sources_html}"""

    return html, 200, {"Content-Type": "text/html"}


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

    settings, products = load_config(CONFIG_PATH)
    product = next((p for p in products if p.slug == slug), None)
    if product is None:
        return jsonify({"ok": False, "error": "Card not found"}), 404

    # Update search_terms
    product = Product(
        title=product.title,
        own_price_idr=product.own_price_idr,
        tokopedia_url=product.tokopedia_url,
        search_terms=[search_term] if search_term else [],
        sources=product.sources,
    )
    products = [p if p.slug != slug else product for p in products]
    save_config(CONFIG_PATH, settings, products)

    return jsonify({"ok": True}), 200


@app.route("/run/<slug>", methods=["POST"])
def run_single_card(slug: str):
    """Re-run price check for a single card."""
    from .config import load_config
    from .analyze import analyze_product
    from .ai import attach_ai_summaries
    from .history import save_run
    from .reports import write_reports
    from .scrapers import MarketplaceScraper

    _, products = load_config(CONFIG_PATH)
    product = next((p for p in products if p.slug == slug), None)
    if product is None:
        return jsonify({"ok": False, "error": "Card not found"}), 404

    settings = {}
    scraper = MarketplaceScraper(settings)
    run_at = utc_now()
    source_results = [scraper.scrape(source) for source in product.sources]
    analyses = [analyze_product(product, source_results, run_at, settings)]
    analyses, ai_warnings = attach_ai_summaries(analyses)
    save_run(analyses)
    write_reports(analyses, analyses[0].run_at.isoformat())
    return jsonify({"ok": True, "title": product.title})


@app.route("/run", methods=["POST"])
def run_scheduler():
    global _scheduler_pid
    import sys
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