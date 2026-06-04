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


def metric_card(label: str, value: str, hint: str = "", tone: str = "neutral") -> str:
    return f"""
    <div class="metric-card metric-card--{h(tone)}">
      <span class="metric-label">{h(label)}</span>
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


def action_badge(action: str) -> str:
    tones = {
        "Lower price": "danger",
        "Raise price": "warning",
        "Missing market data": "muted",
        "Aligned": "success",
    }
    return badge(action, tones.get(action, "neutral"))


def dashboard_fragment(
    *,
    total_listings: int,
    portfolio_value: int,
    market_value: int,
    alerts_count: int,
    latest_run: dict[str, Any] | None,
) -> str:
    failures = latest_run.get("failures", []) if latest_run else []
    run_status = latest_run.get("status", "No runs") if latest_run else "No runs"
    run_time = latest_run.get("run_at", "-") if latest_run else "-"
    failure_rows = []
    for failure in failures[:5]:
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

    return (
        metric_grid(
            [
                metric_card("Active listings", f"{total_listings:,}", "Live cards in your store"),
                metric_card("Portfolio value", idr(portfolio_value), "Sum of Tokopedia prices"),
                metric_card("Market value", idr(market_value), "Sum of latest global averages"),
                metric_card("Active alerts", f"{alerts_count:,}", "Cards priced above market", "danger" if alerts_count else "success"),
                metric_card("Latest run", h(run_status).title(), run_time, "success" if run_status == "complete" else "warning"),
            ]
        )
        + panel("Source Health", failures_body, subtitle="Latest scheduler trace and marketplace access status.")
    )


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


def identity_panel(product: Any) -> str:
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
    return panel("Card Identity", f'<dl class="identity-list">{body}</dl>')


def card_detail_fragment(
    *,
    product: Any,
    info: dict[str, Any],
    observations: list[dict[str, Any]],
    chart_exists: bool,
    price_history: list[dict[str, Any]] | None = None,
    trend_7d: float | None = None,
    trend_30d: float | None = None,
    suggested: dict[str, int | None] | None = None,
) -> str:
    price_history = price_history or []
    suggested = suggested or {"quick_sale": None, "normal": None, "max_profit": None}
    latest_snapshot = price_history[0] if price_history else {}
    latest_tokopedia_price = latest_snapshot.get("tokopedia_price", product.own_price_idr)
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
            ]
        )

    search_term = product.search_terms[0] if product.search_terms else ""
    search_editor = ""
    if not is_sold:
        search_editor = field_row(
            "Search keyword",
            (
                f'<input id="search-term-input" class="input" type="text" value="{h(search_term)}">'
                f'{button("Save", onclick=f"updateSearchTerm(\\'{h(product.slug)}\\')", variant="secondary")}'
            ),
            "Used for competitor search URLs.",
        )

    metrics = metric_grid(
        [
            metric_card("Latest Tokopedia price", idr(latest_tokopedia_price)),
            metric_card("Latest market avg", idr(latest_market_avg)),
            metric_card("Delta", pct(info.get("price_delta_percent"))),
            metric_card("7 day market trend", pct(trend_7d)),
            metric_card("30 day market trend", pct(trend_30d)),
            metric_card("Status", badge("Sold", "danger") if is_sold else alert_badge(alert, alert_label)),
        ]
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
        + suggested_price_panel(suggested)
        + identity_panel(product)
        + chart
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


def sold_cards_fragment(products: list[Any]) -> str:
    if not products:
        return empty_state("No sold cards", "Cards marked sold or delisted will appear here.")
    cards = []
    for product in products:
        sold_date = product.sold_at[:10] if product.sold_at else "-"
        cards.append(
            f"""
            <article class="product-card product-card--sold">
              <div class="product-card__header">
                <a class="product-card__title" href="/cards/{h(product.slug)}">{h(product.title)}</a>
                {badge("Sold", "danger")}
              </div>
              <div class="product-card__meta">{h(product.language)}</div>
              <div class="mini-metrics">
                {metric_card("Your price", idr(product.own_price_idr))}
                {metric_card("Sold at", h(sold_date))}
              </div>
              <div class="card-actions">{button("Mark Active", onclick=f"revertSold('{h(product.slug)}')", variant="secondary")}</div>
            </article>"""
        )
    return f'<div class="cards-grid">{"".join(cards)}</div>'


def opportunities_fragment(products: list[dict[str, Any]]) -> str:
    rows = []
    for product in products:
        rows.append({
            "title": product.get("title", product["slug"]),
            "slug": product["slug"],
            "set": "-",
            "global_avg": product.get("global_average_idr"),
            "local_supply": "-",
            "score": "-",
            "note": "Review as potential import if global listings are liquid and local supply is thin.",
        })
    return panel(
        "Opportunity Review Queue",
        data_table(
            ["title", "set", "global_avg", "local_supply", "score", "note"],
            rows,
            class_name="data-table--compact",
            columns=[
                {"field": "title", "headerName": "Card", "cellRenderer": "cardLink", "flex": 2, "minWidth": 280},
                {"field": "set", "headerName": "Set", "width": 100},
                {"field": "global_avg", "headerName": "Global Avg", "cellRenderer": "moneyValue", "width": 150, "type": "numericColumn"},
                {"field": "local_supply", "headerName": "Local Supply", "width": 140},
                {"field": "score", "headerName": "Score", "width": 100},
                {"field": "note", "headerName": "Note", "flex": 2, "minWidth": 320},
            ],
        ),
        subtitle="First-pass candidates, not automatic buy recommendations.",
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
