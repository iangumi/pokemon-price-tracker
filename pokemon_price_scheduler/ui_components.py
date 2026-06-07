from __future__ import annotations

import html
import json
from collections.abc import Iterable
from typing import Any

from .reports import idr, pct


def h(value: object) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def attrs(**values: object) -> str:
    rendered = []
    for key, value in values.items():
        if value is None or value is False:
            continue
        name = key[:-1] if key.endswith("_") else key
        name = name.replace("_", "-")
        if value is True:
            rendered.append(name)
        else:
            rendered.append(f'{name}="{h(value)}"')
    return (" " + " ".join(rendered)) if rendered else ""


def button(label: str, *, onclick: str = "", variant: str = "primary", element_id: str = "") -> str:
    return (
        f'<button{attrs(id=element_id or None, class_=f"btn btn--{variant}", onclick=onclick or None)}>'
        f"{h(label)}</button>"
    )


def link_button(label: str, href: str, *, variant: str = "secondary", external: bool = False) -> str:
    target = "_blank" if external else None
    return f'<a{attrs(class_=f"btn btn--{variant}", href=href, target=target)}>{h(label)}</a>'


def badge(label: str, tone: str = "neutral") -> str:
    if not label:
        return '<span class="status-badge status-badge--muted">-</span>'
    return f'<span class="status-badge status-badge--{h(tone)}">{h(label)}</span>'


def alert_badge(level: str, label: str = "") -> str:
    if level == "red":
        return badge(label or "Price too high", "danger")
    if level == "amber":
        return badge(label or "Price a bit high", "warning")
    return badge("Aligned", "muted")


def source_badge(kind: str, ok: bool | None = None) -> str:
    tone = "neutral"
    label = kind.replace("_", " ")
    if ok is True:
        tone = "success"
    elif ok is False:
        tone = "danger"
    return badge(label, tone)


def toolbar(*items: str) -> str:
    return f'<div class="toolbar">{"".join(item for item in items if item)}</div>'


def panel(title: str, body: str, *, subtitle: str = "", class_name: str = "") -> str:
    subtitle_html = f'<p class="panel-subtitle">{h(subtitle)}</p>' if subtitle else ""
    return f"""
    <section class="panel {h(class_name)}">
      <div class="panel-header">
        <h2>{h(title)}</h2>
        {subtitle_html}
      </div>
      <div class="panel-body">{body}</div>
    </section>"""


def empty_state(title: str, message: str, *, action: str = "") -> str:
    return f"""
    <div class="empty-state">
      <strong>{h(title)}</strong>
      <span>{h(message)}</span>
      {action}
    </div>"""


def inline_icon(name: str) -> str:
    paths = {
        "store": '<path d="M4 9h16l-2-5H6L4 9Z"/><path d="M6 9v10h12V9"/><path d="M9 19v-6h6v6"/>',
        "cards": '<rect x="7" y="4" width="10" height="14" rx="1"/><path d="M4 7h3M17 7h3M10 8h4M10 12h4"/>',
        "market": '<path d="M4 17h16"/><path d="M6 14l4-4 3 3 5-7"/><path d="M16 6h2v2"/>',
        "alert": '<path d="M12 4 4 18h16L12 4Z"/><path d="M12 9v4M12 16h.01"/>',
        "run": '<path d="M5 12a7 7 0 0 1 12-5"/><path d="M17 7V4h3"/><path d="M19 12a7 7 0 0 1-12 5"/><path d="M7 17v3H4"/>',
        "queue": '<path d="M6 6h12M6 12h12M6 18h12"/><path d="M3 6h.01M3 12h.01M3 18h.01"/>',
        "report": '<path d="M7 3h7l3 3v15H7V3Z"/><path d="M14 3v4h4M9 12h6M9 16h6"/>',
    }
    path = paths.get(name, paths["cards"])
    return f'<span class="ui-icon ui-icon--{h(name)}" aria-hidden="true"><svg viewBox="0 0 24 24" focusable="false">{path}</svg></span>'


def compact_millions(value: int | None) -> str:
    if value is None:
        return "-"
    return f"Rp {value / 1_000_000:.1f}M"


def metric_card(label: str, value: str, hint: str = "", tone: str = "neutral", *, icon: str = "") -> str:
    icon_html = inline_icon(icon) if icon else ""
    return f"""
    <div class="metric-card metric-card--{h(tone)}">
      <span class="metric-label">{icon_html}{h(label)}</span>
      <strong class="metric-value">{value}</strong>
      <span class="metric-hint">{h(hint)}</span>
    </div>"""


def metric_grid(cards: Iterable[str]) -> str:
    return f'<section class="metric-grid">{"".join(cards)}</section>'


def data_table(
    headers: list[str],
    rows: list[dict[str, Any]],
    *,
    table_id: str = "",
    class_name: str = "",
    columns: list[dict[str, Any]] | None = None,
) -> str:
    if not rows:
        return empty_state("No data yet", "Run the scheduler or add cards to populate this table.")
    column_defs = columns or [{"field": header, "headerName": header} for header in headers]
    column_defs = [column for column in column_defs if _column_has_values(column, rows)]
    return f"""
    <div class="table-shell grid-shell {h(class_name)}">
      <div{attrs(id=table_id or None, class_=f"ag-grid-host ag-theme-quartz {class_name}".strip(), data_columns=json.dumps(column_defs), data_rows=json.dumps(rows), data_grid_id=table_id or None)}></div>
    </div>"""


def _column_has_values(column: dict[str, Any], rows: list[dict[str, Any]]) -> bool:
    if column.get("alwaysRender"):
        return True
    field = column.get("field")
    if not field:
        return True
    empty_values = {None, "", "-", "N/A", "n/a"}
    return any(row.get(field) not in empty_values for row in rows)


def field_row(label: str, control: str, help_text: str = "") -> str:
    help_html = f'<span class="field-help">{h(help_text)}</span>' if help_text else ""
    return f"""
    <div class="field-row">
      <label>{h(label)}</label>
      <div class="field-control">{control}{help_html}</div>
    </div>"""


def format_trend(value: float | None) -> str:
    if value is None:
        return '<span class="trend trend--flat">-</span>'
    direction = "up" if value > 0 else "down" if value < 0 else "flat"
    return f'<span class="trend trend--{direction}">{value:+.1f}%</span>'


def format_money_or_missing(value: int | None) -> str:
    return "Insufficient market data" if value is None else idr(value)


def first_positive_int(*values: int | None) -> int | None:
    for value in values:
        if isinstance(value, int) and value > 0:
            return value
    return None


def action_badge(action: str) -> str:
    tones = {
        "Lower price": "danger",
        "Raise price": "warning",
        "Missing market data": "muted",
        "Aligned": "success",
    }
    return badge(action, tones.get(action, "neutral"))


def source_health_panel(latest_run: dict[str, Any] | None) -> str:
    failures = latest_run.get("failures", []) if latest_run else []
    failure_rows = []
    for failure in failures[:20]:
        failure_rows.append({
            "source": failure.get("source_name", "-"),
            "failure": failure.get("failure_kind") or failure.get("status") or "error",
            "backend": failure.get("fetch_backend", "-"),
            "product": failure.get("product_slug", "-"),
        })

    failures_body = data_table(
        ["source", "failure", "backend", "product"],
        failure_rows,
        class_name="data-table--compact",
        columns=[
            {"field": "source", "headerName": "Source", "flex": 1},
            {"field": "failure", "headerName": "Failure", "cellRenderer": "badgeDanger", "width": 150},
            {"field": "backend", "headerName": "Backend", "width": 130},
            {"field": "product", "headerName": "Product", "flex": 2},
        ],
    ) if failures else empty_state("No source failures", "Latest run completed without recorded source errors.")

    return panel("Source Health", failures_body, subtitle="Latest scheduler trace and marketplace access status.")


def reports_fragment(latest_run: dict[str, Any] | None) -> str:
    run_status = latest_run.get("status", "No runs") if latest_run else "No runs"
    run_time = latest_run.get("run_at", "-") if latest_run else "-"
    return (
        panel(
            "Report Files",
            metric_grid(
                [
                    metric_card("Latest run", h(run_status).title(), run_time, "success" if run_status == "complete" else "warning", icon="run"),
                    metric_card("Markdown report", "latest.md", "Open the latest generated report", icon="report"),
                    metric_card("CSV export", "latest.csv", "Download the latest tabular report", icon="report"),
                ]
            )
            + toolbar(
                link_button("Open Markdown", "/latest.md", variant="secondary", external=True),
                link_button("Open CSV", "/latest.csv", variant="secondary", external=True),
            ),
            subtitle="Generated scheduler outputs and source diagnostics.",
        )
        + source_health_panel(latest_run)
    )


def dashboard_active_cards_preview(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return empty_state("No active cards", "Add Tokopedia listings to populate active cards.")
    body = []
    for row in rows[:6]:
        body.append(
            f"""
            <tr>
              <td><a class="table-title" href="/cards/{h(row.get('slug', ''))}">{h(row.get('title', '-'))}</a></td>
              <td class="table-money">{h(idr(row.get('own_price')))}</td>
              <td>{format_trend(row.get('delta'))}</td>
              <td>{alert_badge(row.get('alert', 'none'), row.get('alert_label', ''))}</td>
            </tr>"""
        )
    return f"""
    <div class="dashboard-preview-table">
      <table>
        <thead><tr><th>Card</th><th>Your Price</th><th>Delta</th><th>Alert</th></tr></thead>
        <tbody>{"".join(body)}</tbody>
      </table>
    </div>
    {toolbar(link_button("View All Cards", "/cards", variant="secondary"))}"""


def _repricing_priority(row: dict[str, Any]) -> tuple[int, float]:
    priorities = {"Lower price": 0, "Raise price": 1, "Missing market data": 2, "Aligned": 3}
    action = row.get("recommended_action", "Aligned")
    delta = row.get("delta_percent")
    abs_delta = abs(float(delta)) if delta is not None else -1.0
    return priorities.get(action, 4), -abs_delta


def dashboard_repricing_preview(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return empty_state("No repricing data", "Run the scheduler to calculate repricing actions.")
    body = []
    short_actions = {
        "Lower price": "Lower",
        "Raise price": "Raise",
        "Missing market data": "Missing",
        "Aligned": "Aligned",
    }
    for row in sorted(rows, key=_repricing_priority)[:6]:
        action = row.get("recommended_action", "Aligned")
        body.append(
            f"""
            <tr>
              <td><a class="table-title" href="/cards/{h(row.get('slug', ''))}">{h(row.get('title', '-'))}</a></td>
              <td class="table-money">{h(idr(row.get('tokopedia_price')))}</td>
              <td>{format_trend(row.get('delta_percent'))}</td>
              <td>{badge(short_actions.get(action, action), {"Lower price": "danger", "Raise price": "warning", "Missing market data": "muted", "Aligned": "success"}.get(action, "neutral"))}</td>
            </tr>"""
        )
    return f"""
    <div class="dashboard-preview-table">
      <table>
        <thead><tr><th>Card</th><th>Tokopedia</th><th>Delta</th><th>Action</th></tr></thead>
        <tbody>{"".join(body)}</tbody>
      </table>
    </div>
    {toolbar(link_button("Open Repricing Queue", "/repricing", variant="secondary"))}"""


def dashboard_fragment(
    *,
    total_listings: int,
    portfolio_value: int,
    market_value: int,
    alerts_count: int,
    latest_run: dict[str, Any] | None,
    active_cards: list[dict[str, Any]] | None = None,
    repricing_rows: list[dict[str, Any]] | None = None,
) -> str:
    run_status = latest_run.get("status", "No runs") if latest_run else "No runs"
    run_time = latest_run.get("run_at", "-") if latest_run else "-"
    signals = panel(
        "Live Store Signals",
        metric_grid(
            [
                metric_card("Active listings", f"{total_listings:,}", "Live cards in your store", icon="store"),
                metric_card("Portfolio value", compact_millions(portfolio_value), "Sum of Tokopedia prices", icon="cards"),
                metric_card("Market value", compact_millions(market_value), "Sum of latest global averages", icon="market"),
                metric_card("Active alerts", f"{alerts_count:,}", "Cards priced above market", "danger" if alerts_count else "success", icon="alert"),
                metric_card("Latest run", h(run_status).title(), run_time, "success" if run_status == "complete" else "warning", icon="run"),
            ]
        ),
        subtitle="Live operating signals from active Tokopedia listings.",
        class_name="live-store-signals",
    )
    previews = f"""
    <section class="dashboard-preview-grid">
      {panel("Active Cards", dashboard_active_cards_preview(active_cards or []), subtitle="Highest value active listings.", class_name="dashboard-preview-panel")}
      {panel("Repricing Queue", dashboard_repricing_preview(repricing_rows or []), subtitle="Actionable pricing changes from current market averages.", class_name="dashboard-preview-panel")}
    </section>"""
    return signals + previews


def cards_fragment(products: list[Any], data_by_slug: dict[str, dict[str, Any]]) -> str:
    rows = []
    for product in products:
        info = data_by_slug.get(product.slug, {})
        global_avg = info.get("global_average_idr")
        delta = info.get("price_delta_percent")
        alert = info.get("alert_level", "none")
        alert_label = info.get("alert_label", "")
        rows.append({
            "title": product.title,
            "slug": product.slug,
            "language": product.language or "-",
            "own_price": product.own_price_idr,
            "own_price_display": idr(product.own_price_idr),
            "market_avg": global_avg,
            "market_avg_display": idr(global_avg),
            "delta": delta,
            "delta_display": pct(delta),
            "alert": alert,
            "alert_label": alert_label or "Aligned",
            "market_trend": info.get("market_trend_percent"),
        })
    content = toolbar(
        button("Sync Store", onclick="syncNewProducts()", variant="secondary"),
        button("Add Card", onclick="openAddCardModal()", variant="primary"),
    ) + data_table(
        ["title", "own_price", "market_avg", "delta", "alert", "market_trend"],
        rows,
        table_id="cards-table",
        class_name="cards-data-grid",
        columns=[
            {"field": "title", "headerName": "Card", "cellRenderer": "cardLink", "flex": 3, "minWidth": 420, "wrapText": True, "autoHeight": True},
            {"field": "own_price", "headerName": "Your Price", "cellRenderer": "moneyValue", "flex": 1, "minWidth": 150, "type": "numericColumn"},
            {"field": "market_avg", "headerName": "Market Avg", "cellRenderer": "moneyValue", "flex": 1, "minWidth": 150, "type": "numericColumn"},
            {"field": "delta", "headerName": "Delta", "cellRenderer": "percentValue", "flex": 1, "minWidth": 140, "type": "numericColumn"},
            {"field": "alert", "headerName": "Alert", "cellRenderer": "alertBadge", "flex": 1, "minWidth": 150, "alwaysRender": True},
            {"field": "market_trend", "headerName": "Market Trend", "valueFormatter": "pct", "cellRenderer": "trend", "flex": 1, "minWidth": 150, "type": "numericColumn"},
        ],
    )
    return f'<section class="cards-page">{content}</section>'


def identity_panel(product: Any, image_url: str = "") -> str:
    identity = product.card_identity
    items = [
        ("Name", identity.name or product.title),
        ("Set", identity.set_symbol or "-"),
        ("Number", identity.card_number or "-"),
        ("Rarity", identity.rarity or "-"),
        ("Language", identity.language or "-"),
        ("Condition", identity.condition or "-"),
        ("Added", product.added_at[:10] if product.added_at else "-"),
        ("Sold", product.sold_at[:10] if product.sold_at else "-"),
    ]
    body = "".join(f"<dt>{h(label)}</dt><dd>{h(value)}</dd>" for label, value in items)
    image_block = ""
    if image_url:
        image_block = f'''
        <div class="identity-picture-block identity-media">
          <img class="card-image" src="{h(image_url)}" alt="Product image for {h(product.title)}">
        </div>'''
    else:
        image_block = '''
        <div class="identity-picture-block identity-media identity-media--empty">
          <span>No product image cached yet</span>
        </div>'''
    return panel(
        "Card Identity",
        f'<div class="identity-layout">{image_block}<div class="identity-detail-block"><dl class="identity-list">{body}</dl></div></div>',
    )


def card_detail_fragment(
    *,
    product: Any,
    info: dict[str, Any],
    observations: list[dict[str, Any]],
    chart_exists: bool,
    image_url: str = "",
    price_history: list[dict[str, Any]] | None = None,
    trend_7d: float | None = None,
    trend_30d: float | None = None,
    suggested: dict[str, int | None] | None = None,
) -> str:
    price_history = price_history or []
    suggested = suggested or {"quick_sale": None, "normal": None, "max_profit": None}
    latest_snapshot = price_history[0] if price_history else {}
    latest_tokopedia_price = first_positive_int(latest_snapshot.get("tokopedia_price"), product.own_price_idr)
    latest_market_avg = latest_snapshot.get("market_avg_price", info.get("global_average_idr"))
    is_sold = product.status == "sold"
    alert = info.get("alert_level", "none")
    alert_label = info.get("alert_label", "")
    tokopedia_url = product.tokopedia_url or next((s.url for s in product.sources if s.kind == "tokopedia_find"), "")
    actions = [link_button("Open Tokopedia", tokopedia_url, external=True)]
    if not is_sold:
        actions.extend(
            [
                button("Refresh Competitors", onclick=f"refreshCard('{h(product.slug)}')", variant="primary", element_id="refresh-btn"),
                button("Sync Store Price", onclick=f"updatePrice('{h(product.slug)}')", variant="secondary", element_id="update-price-btn"),
                button("Mark Sold", onclick=f"openMarkSoldModal('{h(product.slug)}')", variant="secondary"),
            ]
        )
    else:
        actions.append(button("Edit Sale", onclick=f"openEditSaleModal('{h(product.slug)}')", variant="secondary"))

    search_term = product.search_terms[0] if product.search_terms else ""
    search_editor = ""
    if not is_sold:
        save_onclick = f'updateSearchTerm("{h(product.slug)}")'
        search_editor = field_row(
            "Search keyword",
            (
                f'<input id="search-term-input" class="input" type="text" value="{h(search_term)}">'
                f'{button("Save", onclick=save_onclick, variant="secondary")}'
            ),
            "Used for competitor search URLs.",
        )

    metrics = panel(
        "Price Review Snapshot",
        metric_grid(
            [
                metric_card("Latest Tokopedia price", format_money_or_missing(latest_tokopedia_price), icon="store"),
                metric_card("Latest market avg", idr(latest_market_avg), icon="market"),
                metric_card("Delta", pct(info.get("price_delta_percent")), icon="alert"),
                metric_card("7 day market trend", pct(trend_7d), icon="run"),
                metric_card("30 day market trend", pct(trend_30d), icon="run"),
                metric_card("Status", badge("Sold", "danger") if is_sold else alert_badge(alert, alert_label), icon="queue"),
            ]
        ),
        subtitle="Latest saved scheduler snapshot and market movement.",
        class_name="detail-review-panel",
    )

    chart = ""
    if chart_exists:
        chart = panel(
            "Price History",
            f'<img class="chart-image" src="/charts/{h(product.slug)}.svg" alt="Price chart for {h(product.title)}">',
        )

    return (
        toolbar(*actions)
        + search_editor
        + metrics
        + identity_panel(product, image_url=image_url)
        + chart
        + suggested_price_panel(suggested)
        + price_history_panel(price_history)
        + source_evidence_panel(observations)
    )


def suggested_price_panel(suggested: dict[str, int | None]) -> str:
    return panel(
        "Suggested Tokopedia Price",
        metric_grid(
            [
                metric_card("Quick sale", format_money_or_missing(suggested.get("quick_sale")), "Market average x 0.92"),
                metric_card("Normal", format_money_or_missing(suggested.get("normal")), "Market average x 0.98"),
                metric_card("Max profit", format_money_or_missing(suggested.get("max_profit")), "Market average x 1.05"),
            ]
        ),
        subtitle="Suggestions are hidden when market average is unavailable.",
    )


def price_history_panel(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return panel("Price History", empty_state("No price history yet", "Run the scheduler to create price snapshots."))
    newest_first = rows[:30]
    table_rows = []
    chart_points = list(reversed(newest_first[:30]))
    for row in newest_first:
        table_rows.append(
            {
                "created_at": row["created_at"][:19].replace("T", " "),
                "tokopedia_price": row.get("tokopedia_price"),
                "market_avg_price": row.get("market_avg_price"),
                "delta_percent": row.get("delta_percent"),
                "alert_status": row.get("alert_status", "none"),
            }
        )
    history_table = data_table(
        ["created_at", "tokopedia_price", "market_avg_price", "delta_percent", "alert_status"],
        table_rows,
        class_name="data-table--compact",
        columns=[
            {"field": "created_at", "headerName": "Snapshot", "flex": 2, "minWidth": 180},
            {"field": "tokopedia_price", "headerName": "Tokopedia Price", "cellRenderer": "moneyValue", "flex": 1, "minWidth": 160, "type": "numericColumn"},
            {"field": "market_avg_price", "headerName": "Market Avg", "cellRenderer": "moneyValue", "flex": 1, "minWidth": 150, "type": "numericColumn"},
            {"field": "delta_percent", "headerName": "Delta", "cellRenderer": "percentValue", "flex": 1, "minWidth": 120, "type": "numericColumn"},
            {"field": "alert_status", "headerName": "Alert", "cellRenderer": "alertBadge", "flex": 1, "minWidth": 130},
        ],
    )
    chart = price_history_chart(chart_points)
    return panel(
        "Price History",
        chart + history_table,
        subtitle="One snapshot is saved for each card after every scheduler run.",
    )


def price_history_chart(rows: list[dict[str, Any]]) -> str:
    points = [row for row in rows if row.get("market_avg_price") is not None or row.get("tokopedia_price") is not None]
    if len(points) < 2:
        return ""
    width = 720
    height = 180
    pad = 18
    values = []
    for row in points:
        values.append(row.get("tokopedia_price"))
        if row.get("market_avg_price") is not None:
            values.append(row.get("market_avg_price"))
    values = [int(value) for value in values if value is not None]
    if not values:
        return ""
    low = min(values)
    high = max(values)
    span = max(high - low, 1)

    def coords(key: str) -> str:
        coords_list = []
        for index, row in enumerate(points):
            value = row.get(key)
            if value is None:
                continue
            x = pad + (index / max(len(points) - 1, 1)) * (width - pad * 2)
            y = height - pad - ((int(value) - low) / span) * (height - pad * 2)
            coords_list.append(f"{x:.1f},{y:.1f}")
        return " ".join(coords_list)

    own_points = coords("tokopedia_price")
    market_points = coords("market_avg_price")
    return f"""
    <div class="chart-image price-history-chart">
      <svg viewBox="0 0 {width} {height}" role="img" aria-label="Price history line chart">
        <line x1="{pad}" y1="{height - pad}" x2="{width - pad}" y2="{height - pad}" stroke="#33404c" />
        <polyline points="{h(own_points)}" fill="none" stroke="#93c5fd" stroke-width="3" />
        <polyline points="{h(market_points)}" fill="none" stroke="#22c55e" stroke-width="3" />
        <text x="{pad}" y="16" fill="#93c5fd" font-size="12">Tokopedia</text>
        <text x="110" y="16" fill="#22c55e" font-size="12">Market avg</text>
      </svg>
    </div>"""


def source_evidence_panel(observations: list[dict[str, Any]]) -> str:
    if not observations:
        return panel(
            "Source Evidence",
            empty_state("No observations yet", "Refresh competitor prices to populate source evidence."),
        )
    rows = []
    for obs in sorted(observations, key=lambda item: item["price_idr"], reverse=True)[:30]:
        used = bool(obs.get("is_legit"))
        rows.append({
            "title": obs.get("title") or obs.get("source_name"),
            "url": obs.get("url", ""),
            "price": obs.get("price_idr"),
            "source": obs.get("source_kind", "-"),
            "decision": "Used" if used else "Filtered",
            "used": used,
        })
    return panel(
        "Source Evidence",
        data_table(
            ["title", "price", "source", "decision"],
            rows,
            class_name="data-table--compact",
            columns=[
                {"field": "title", "headerName": "Listing", "cellRenderer": "externalLink", "flex": 2, "minWidth": 300},
                {"field": "price", "headerName": "Price", "cellRenderer": "moneyValue", "width": 150, "type": "numericColumn"},
                {"field": "source", "headerName": "Source", "cellRenderer": "sourceBadge", "width": 170},
                {"field": "decision", "headerName": "Decision", "cellRenderer": "decisionBadge", "width": 130},
            ],
        ),
        subtitle="Parsed marketplace observations from the latest saved run.",
    )


def sold_cards_fragment(products: list[Any], summary: dict[str, Any] | None = None) -> str:
    summary = summary or {"sold_count": 0, "net_income_idr": 0, "weekly": [], "monthly": []}
    if not products:
        return panel(
            "Sales Summary",
            metric_grid(
                [
                    metric_card("Sold cards", "0", "Completed sale records", icon="cards"),
                    metric_card("Net income", idr(0), "Manual income captured from sales", icon="market"),
                ]
            ),
            subtitle="Income analysis will appear after cards are marked sold.",
        ) + empty_state("No sold cards", "Cards marked sold or delisted will appear here.")
    monthly = summary.get("monthly") or []
    period_note = "No monthly income yet"
    if monthly:
        period_note = ", ".join(
            f"{h(row.get('period', '-'))}: {h(idr(row.get('net_income_idr')))}"
            for row in monthly[:3]
        )
    summary_panel = panel(
        "Sales Summary",
        metric_grid(
            [
                metric_card("Sold cards", f"{int(summary.get('sold_count') or 0):,}", "Sales with income records", icon="cards"),
                metric_card("Net income", idr(summary.get("net_income_idr") or 0), "Total manually recorded income", icon="market"),
                metric_card("Monthly view", str(len(monthly)), period_note, icon="run"),
            ]
        ),
        subtitle="Income metrics use sold date and manually entered net income.",
    )
    cards = []
    for product in products:
        if isinstance(product, dict):
            title = product.get("title", "-")
            slug = product.get("slug", "")
            language = product.get("language", "-")
            price = product.get("own_price_idr")
            sold_at = product.get("sold_at", "")
            bought_at_price = product.get("bought_at_price_idr")
            sold_price = product.get("sold_price_idr")
            net_income = product.get("net_income_idr")
        else:
            title = product.title
            slug = product.slug
            language = product.language
            price = product.own_price_idr
            sold_at = product.sold_at
            bought_at_price = None
            sold_price = None
            net_income = None
        sold_date = sold_at[:10] if sold_at else "-"
        sold_value = sold_at[:10] if sold_at else ""
        bought_price_value = "" if bought_at_price is None else str(bought_at_price)
        sold_price_value = "" if sold_price is None else str(sold_price)
        net_income_value = "" if net_income is None else str(net_income)
        cards.append(
            f"""
            <article class="product-card product-card--sold">
              <div class="product-card__header">
                <a class="product-card__title" href="/cards/{h(slug)}">{h(title)}</a>
                {badge("Sold", "danger")}
              </div>
              <div class="product-card__meta">{h(language)}</div>
              <div class="mini-metrics">
                {metric_card("Listing price", idr(price))}
                {metric_card("Sold price", idr(sold_price))}
                {metric_card("Bought price", idr(bought_at_price))}
                {metric_card("Sold at", h(sold_date))}
                {metric_card("Net income", idr(net_income))}
              </div>
              <div class="card-actions">
                {button("Edit Sale", onclick=f"openEditSaleModal('{h(slug)}', '{h(sold_value)}', '{h(sold_price_value)}', '{h(bought_price_value)}', '{h(net_income_value)}')", variant="primary")}
                {button("Mark Active", onclick=f"revertSold('{h(slug)}')", variant="secondary")}
              </div>
            </article>"""
        )
    return summary_panel + f'<div class="cards-grid">{"".join(cards)}</div>'


def opportunities_fragment(opportunities: list[dict[str, Any]]) -> str:
    rows = []
    for opportunity in opportunities:
        rows.append(
            {
                "title": opportunity.get("title") or opportunity.get("card_name"),
                "slug": opportunity["slug"],
                "card_rarity": opportunity.get("card_rarity", "-"),
                "card_language": opportunity.get("card_language", "-"),
                "source": opportunity.get("source", "-"),
                "link": opportunity.get("link", ""),
                "price_idr": opportunity.get("price_idr"),
                "status": opportunity.get("status", "open"),
            }
        )
    content = toolbar(button("Add Buy List Card", onclick="openOpportunityModal()", variant="primary")) + data_table(
        ["title", "card_rarity", "card_language", "source", "price_idr", "status"],
        rows,
        class_name="data-table--compact",
        columns=[
            {"field": "title", "headerName": "Card", "cellRenderer": "opportunityLink", "flex": 2, "minWidth": 280},
            {"field": "card_rarity", "headerName": "Rarity", "width": 120},
            {"field": "card_language", "headerName": "Language", "width": 130},
            {"field": "source", "headerName": "Source", "width": 150},
            {"field": "price_idr", "headerName": "Price", "cellRenderer": "moneyValue", "width": 150, "type": "numericColumn"},
            {"field": "status", "headerName": "Status", "cellRenderer": "statusBadge", "width": 140, "alwaysRender": True},
        ],
    )
    return panel(
        "Buy List Opportunities",
        content if rows else toolbar(button("Add Buy List Card", onclick="openOpportunityModal()", variant="primary"))
        + empty_state("No opportunities yet", "Add a buy-list card to start tracking purchase opportunities."),
        subtitle="Cards you are considering buying before they become owned inventory or active listings.",
    )


def opportunity_detail_fragment(opportunity: dict[str, Any]) -> str:
    status = opportunity.get("status", "open")
    facts = metric_grid(
        [
            metric_card("Opportunity price", idr(opportunity.get("price_idr")), "Current buy-list price", icon="market"),
            metric_card("Rarity", h(opportunity.get("card_rarity", "-")), "Card rarity", icon="cards"),
            metric_card("Language", h(opportunity.get("card_language", "-")), "Card language", icon="cards"),
            metric_card("Status", badge(status.title(), "success" if status == "converted" else "warning"), "Buying pipeline status", icon="queue"),
        ]
    )
    detail_rows = [
        ("Card", opportunity.get("card_name", "-")),
        ("Rarity", opportunity.get("card_rarity", "-")),
        ("Language", opportunity.get("card_language", "-")),
        ("Source", opportunity.get("source", "-")),
        ("Price", idr(opportunity.get("price_idr"))),
        ("Created", opportunity.get("created_at", "")[:10] if opportunity.get("created_at") else "-"),
        ("Converted", opportunity.get("converted_at", "")[:10] if opportunity.get("converted_at") else "-"),
    ]
    source_link = link_button("Open Source", opportunity.get("link", ""), variant="secondary", external=True) if opportunity.get("link") else ""
    convert = ""
    if status != "converted":
        convert = button(
            "Convert to Inventory",
            onclick=f"openConvertOpportunityModal('{h(opportunity.get('slug', ''))}', '{h(opportunity.get('price_idr', ''))}')",
            variant="primary",
        )
    body = "".join(f"<dt>{h(label)}</dt><dd>{value if label == 'Price' else h(value)}</dd>" for label, value in detail_rows)
    return (
        toolbar(link_button("Back to Opportunities", "/opportunities", variant="secondary"), source_link, convert)
        + panel("Opportunity Snapshot", facts, subtitle="Buy-list details before conversion.")
        + panel("Card Opportunity Detail", f'<dl class="identity-list">{body}</dl>')
    )


def inventory_fragment(rows: list[dict[str, Any]]) -> str:
    table_rows = [
        {
            "title": row.get("title", "-"),
            "slug": row.get("slug", ""),
            "card_rarity": row.get("card_rarity", "-"),
            "card_language": row.get("card_language", "-"),
            "bought_at_price_idr": row.get("bought_at_price_idr"),
            "quantity": row.get("quantity"),
            "status": row.get("status"),
            "source": row.get("source", "-"),
            "type": row.get("type", "-"),
        }
        for row in rows
    ]
    return panel(
        "Owned Inventory",
        data_table(
            ["title", "card_rarity", "card_language", "bought_at_price_idr", "quantity", "status", "source", "type"],
            table_rows,
            class_name="data-table--compact",
            columns=[
                {"field": "title", "headerName": "Card", "cellRenderer": "cardLink", "flex": 2, "minWidth": 280},
                {"field": "card_rarity", "headerName": "Rarity", "width": 120},
                {"field": "card_language", "headerName": "Language", "width": 130},
                {"field": "bought_at_price_idr", "headerName": "Bought Price", "cellRenderer": "moneyValue", "width": 160, "type": "numericColumn"},
                {"field": "quantity", "headerName": "Qty", "width": 90, "type": "numericColumn"},
                {"field": "status", "headerName": "Status", "cellRenderer": "statusBadge", "width": 130, "alwaysRender": True},
                {"field": "source", "headerName": "Source", "width": 170},
                {"field": "type", "headerName": "Type", "width": 120},
            ],
        )
        if table_rows else empty_state("No inventory yet", "Convert an opportunity or add an active listing to populate inventory."),
        subtitle="Owned stock from converted opportunities plus active and sold listing lifecycles.",
    )


def repricing_queue_fragment(rows: list[dict[str, Any]]) -> str:
    summary = {
        "Lower price": 0,
        "Raise price": 0,
        "Missing market data": 0,
        "Aligned": 0,
    }
    if not rows:
        return panel(
            "Repricing Queue",
            empty_state("No repricing data yet", "Run the scheduler to populate the repricing queue."),
        )
    table_rows = []
    for row in rows:
        table_rows.append(
            {
                "title": row["title"],
                "slug": row["slug"],
                "tokopedia_price": row.get("tokopedia_price"),
                "market_avg_price": row.get("market_avg_price"),
                "delta_percent": row.get("delta_percent"),
                "suggested_quick_sale": row.get("suggested_quick_sale"),
                "suggested_normal": row.get("suggested_normal"),
                "suggested_max_profit": row.get("suggested_max_profit"),
                "recommended_action": row.get("recommended_action", "Aligned"),
            }
        )
        action = row.get("recommended_action", "Aligned")
        summary[action] = summary.get(action, 0) + 1
    summary_html = metric_grid(
        [
            metric_card("Need price decrease", f"{summary['Lower price']:,}", "Tokopedia price is above market by more than 10%", "danger" if summary["Lower price"] else "neutral"),
            metric_card("Need price increase", f"{summary['Raise price']:,}", "Tokopedia price is below market by more than 10%", "warning" if summary["Raise price"] else "neutral"),
            metric_card("Missing market data", f"{summary['Missing market data']:,}", "No market average is available", "muted"),
            metric_card("Aligned", f"{summary['Aligned']:,}", "Within +/-10% of market average", "success" if summary["Aligned"] else "neutral"),
        ]
    )
    controls_html = """
    <section class="repricing-controls">
      <div class="control-group">
        <span class="control-label">Filter</span>
        <button class="btn btn--secondary" onclick="filterRepricing('')">All</button>
        <button class="btn btn--secondary" onclick="filterRepricing('Lower price')">Lower price</button>
        <button class="btn btn--secondary" onclick="filterRepricing('Raise price')">Raise price</button>
        <button class="btn btn--secondary" onclick="filterRepricing('Missing market data')">Missing market data</button>
        <button class="btn btn--secondary" onclick="filterRepricing('Aligned')">Aligned</button>
      </div>
      <div class="control-group">
        <span class="control-label">Sort</span>
        <button class="btn btn--secondary" onclick="sortRepricing('delta_desc')">Highest delta</button>
        <button class="btn btn--secondary" onclick="sortRepricing('delta_asc')">Lowest delta</button>
        <button class="btn btn--secondary" onclick="sortRepricing('tokopedia_desc')">Highest card price</button>
        <button class="btn btn--secondary" onclick="sortRepricing('market_desc')">Highest market price</button>
      </div>
    </section>"""
    return panel(
        "Repricing Queue",
        summary_html
        + controls_html
        + data_table(
            [
                "title",
                "tokopedia_price",
                "market_avg_price",
                "delta_percent",
                "suggested_quick_sale",
                "suggested_normal",
                "suggested_max_profit",
                "recommended_action",
            ],
            table_rows,
            table_id="repricing-table",
            columns=[
                {"field": "title", "headerName": "Card", "cellRenderer": "cardLink", "flex": 3, "minWidth": 360, "alwaysRender": True},
                {"field": "tokopedia_price", "headerName": "Tokopedia Price", "cellRenderer": "moneyValue", "flex": 1, "minWidth": 160, "type": "numericColumn", "alwaysRender": True},
                {"field": "market_avg_price", "headerName": "Market Avg", "cellRenderer": "moneyValue", "flex": 1, "minWidth": 150, "type": "numericColumn", "alwaysRender": True},
                {"field": "delta_percent", "headerName": "Delta", "cellRenderer": "percentValue", "flex": 1, "minWidth": 120, "type": "numericColumn", "alwaysRender": True},
                {"field": "suggested_quick_sale", "headerName": "Quick Sale", "cellRenderer": "suggestedMoney", "flex": 1, "minWidth": 170, "type": "numericColumn", "alwaysRender": True},
                {"field": "suggested_normal", "headerName": "Normal", "cellRenderer": "suggestedMoney", "flex": 1, "minWidth": 170, "type": "numericColumn", "alwaysRender": True},
                {"field": "suggested_max_profit", "headerName": "Max Profit", "cellRenderer": "suggestedMoney", "flex": 1, "minWidth": 170, "type": "numericColumn", "alwaysRender": True},
                {"field": "recommended_action", "headerName": "Recommended Action", "cellRenderer": "actionBadge", "flex": 1, "minWidth": 170, "alwaysRender": True},
            ],
        ),
        subtitle="Cards more than 10% above or below market average are queued for action.",
    )
