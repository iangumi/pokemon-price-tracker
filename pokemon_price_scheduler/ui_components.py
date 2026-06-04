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
) -> str:
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
            metric_card("Your price", idr(product.own_price_idr)),
            metric_card("Global avg", idr(info.get("global_average_idr"))),
            metric_card("Delta", pct(info.get("price_delta_percent"))),
            metric_card("Status", badge("Sold", "danger") if is_sold else alert_badge(alert, alert_label)),
        ]
    )

    chart = ""
    if chart_exists:
        chart = panel(
            "Price History",
            f'<img class="chart-image" src="/charts/{h(product.slug)}.svg" alt="Price chart for {h(product.title)}">',
        )

    return toolbar(*actions) + search_editor + metrics + identity_panel(product) + chart + source_evidence_panel(observations)


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
