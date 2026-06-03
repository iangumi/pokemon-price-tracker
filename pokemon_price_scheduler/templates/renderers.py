"""Template renderers using Jinja2 — infrastructure concern."""

from __future__ import annotations

import html
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from ..domain.models import ProductAnalysis

env = Environment(loader=FileSystemLoader(Path(__file__).parent))


def h(value: object) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def idr(value: int | None) -> str:
    if value is None:
        return "-"
    return f"Rp {value:,.0f}".replace(",", ".")


def pct(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:+.1f}%"


def render_dashboard(analyses: list[ProductAnalysis], run_id: int) -> str:
    sorted_analyses = sorted(analyses, key=lambda item: abs(item.price_delta_percent or 0), reverse=True)
    rows = []
    for analysis in sorted_analyses:
        from ..domain.models import alert_label
        identity = analysis.product.card_identity
        rows.append({
            "slug": analysis.product.slug,
            "name": h(identity.name or analysis.product.title),
            "set_symbol": h(identity.set_symbol),
            "rarity": h(identity.rarity),
            "language": h(identity.language),
            "condition": h(identity.condition),
            "own_price": idr(analysis.product.own_price_idr),
            "global_avg": idr(analysis.global_average_idr),
            "delta": pct(analysis.price_delta_percent),
            "alert_level": analysis.alert_level,
            "alert_label": h(alert_label(analysis.alert_level)),
            "chart_path": f"charts/{analysis.product.slug}.svg",
        })

    generated = analyses[0].run_at.isoformat() if analyses else ""
    template = env.get_template("dashboard.html")
    return template.render(
        title="Pokemon Price Dashboard",
        rows=rows,
        run_id=run_id,
        generated=generated,
        nav_class=lambda page: "active" if page == "dash" else "",
    )


def render_card_detail(analysis: ProductAnalysis) -> str:
    identity = analysis.product.card_identity
    from ..domain.models import alert_label

    # Build observation lookup by source name
    observations_by_source = {}
    for result in analysis.source_results:
        observations_by_source[result.source.name] = result.observations

    source_sections = []
    for src in analysis.product.sources:
        obs_list = observations_by_source.get(src.name, [])
        obs_rows = []
        for obs in obs_list[:10]:
            legit = "yes" if obs.is_legit else "filtered"
            obs_rows.append({
                "title": h(obs.title or src.name),
                "url": h(obs.url),
                "price": idr(obs.price_idr),
                "source_kind": h(obs.source_kind),
                "relevance": getattr(obs, "relevance_score", 0),
                "legit": legit,
            })
        source_sections.append({
            "name": h(src.name),
            "url": h(src.url),
            "rows": obs_rows,
            "empty": not obs_rows,
        })

    chart_path = f"../charts/{analysis.product.slug}.svg"
    template = env.get_template("card_detail.html")
    return template.render(
        title=h(identity.name or analysis.product.title),
        product_title=h(analysis.product.title),
        metrics={
            "own_price": idr(analysis.product.own_price_idr),
            "global_avg": idr(analysis.global_average_idr),
            "delta": pct(analysis.price_delta_percent),
            "alert": h(alert_label(analysis.alert_level)),
            "alert_level": analysis.alert_level,
        },
        identity={
            "name": h(identity.name),
            "set_symbol": h(identity.set_symbol),
            "card_number": h(identity.card_number),
            "rarity": h(identity.rarity),
            "language": h(identity.language),
            "condition": h(identity.condition),
        },
        chart_path=chart_path,
        chart_exists=True,
        source_sections=source_sections,
        ai_summary=h(analysis.ai_summary) if analysis.ai_summary else None,
        nav_class=lambda page: "active" if page == "cards" else "",
    )


def render_opportunities(analyses: list[ProductAnalysis]) -> str:
    candidates = []
    for analysis in analyses:
        global_count = sum(
            len(result.observations)
            for result in analysis.source_results
            if result.source.kind != "tokopedia_find"
        )
        local_count = sum(
            len([obs for obs in result.observations if obs.is_legit])
            for result in analysis.source_results
            if result.source.kind == "tokopedia_find"
        )
        if not analysis.global_average_idr:
            continue
        scarcity_score = max(0, 10 - local_count)
        demand_score = min(10, global_count)
        delta_bonus = 2 if (analysis.price_delta_percent or 0) < -10 else 0
        score = scarcity_score + demand_score + delta_bonus
        candidates.append((score, global_count, local_count, analysis))

    rows = []
    for score, global_count, local_count, analysis in sorted(candidates, key=lambda item: item[0], reverse=True)[:50]:
        from ..domain.models import alert_label
        identity = analysis.product.card_identity
        rows.append({
            "slug": analysis.product.slug,
            "name": h(identity.name or analysis.product.title),
            "set_symbol": h(identity.set_symbol),
            "rarity": h(identity.rarity),
            "global_avg": idr(analysis.global_average_idr),
            "global_count": global_count,
            "local_count": local_count,
            "score": score,
        })

    template = env.get_template("opportunities.html")
    return template.render(
        title="Buying Opportunities",
        rows=rows,
        nav_class=lambda page: "active" if page == "ops" else "",
    )
