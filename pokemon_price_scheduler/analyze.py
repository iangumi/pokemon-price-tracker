from __future__ import annotations

from statistics import median

from .models import Product, ProductAnalysis, SourceResult


def score_observations(product: Product, source_results: list[SourceResult]) -> list[SourceResult]:
    identity = product.card_identity
    scored_results: list[SourceResult] = []
    for result in source_results:
        observations = []
        for obs in result.observations:
            score = relevance_score(obs.title, identity.name, identity.set_symbol, identity.rarity, identity.condition)
            observations.append(
                type(obs)(
                    source_name=obs.source_name,
                    source_kind=obs.source_kind,
                    url=obs.url,
                    price_idr=obs.price_idr,
                    title=obs.title,
                    currency=obs.currency,
                    raw_price=obs.raw_price,
                    is_legit=obs.is_legit,
                    relevance_score=score,
                )
            )
        observations.sort(key=lambda item: (abs(item.price_idr - product.own_price_idr), -item.relevance_score))
        scored_results.append(SourceResult(source=result.source, observations=observations[:10], warnings=result.warnings))
    return scored_results


def relevance_score(title: str, name: str, set_symbol: str, rarity: str, condition: str) -> float:
    text = title.lower()
    score = 0.0
    name_tokens = [token for token in name.lower().split() if len(token) > 1]
    if name_tokens:
        score += sum(1 for token in name_tokens if token in text) / len(name_tokens) * 55
    if set_symbol and set_symbol.lower() in text:
        score += 15
    if rarity and rarity.lower() in text:
        score += 10
    if condition and condition.lower() in text:
        score += 20
    return round(score, 2)


def analyze_product(product: Product, source_results: list[SourceResult], run_at, settings: dict) -> ProductAnalysis:
    source_results = score_observations(product, source_results)
    min_ratio = float(settings.get("comparable_min_ratio_to_own", 0.35))
    max_ratio = float(settings.get("comparable_max_ratio_to_own", 8))
    low_bound = product.own_price_idr * min_ratio
    high_bound = product.own_price_idr * max_ratio
    legit_prices = [
        obs.price_idr
        for result in source_results
        for obs in result.observations
        if obs.is_legit and low_bound <= obs.price_idr <= high_bound
    ]
    market_min = min(legit_prices) if legit_prices else None
    market_median = int(median(legit_prices)) if legit_prices else None
    global_average = round(sum(legit_prices) / len(legit_prices)) if legit_prices else None
    threshold = float(settings.get("cheap_threshold_percent", 8))
    alert_threshold = float(settings.get("alert_threshold_percent", 12))

    underpriced_by = None
    underpriced_pct = None
    price_delta_pct = None
    alert_level = "none"
    recommendation = "No reliable market price found yet. Check manually or improve this product's source URLs."
    if global_average:
        price_delta_pct = round(((product.own_price_idr - global_average) / global_average) * 100, 2)
        if abs(price_delta_pct) >= alert_threshold:
            alert_level = "red"
        elif abs(price_delta_pct) >= 10:
            alert_level = "amber"

    if market_median:
        delta = market_median - product.own_price_idr
        pct = (delta / market_median) * 100
        if pct >= threshold:
            underpriced_by = delta
            underpriced_pct = round(pct, 2)
            recommendation = (
                f"Looks underpriced by about {underpriced_pct:.1f}% versus market median. "
                f"Consider raising near Rp {market_median:,.0f}, then leave room for platform fees and negotiation."
            )
        elif pct <= -threshold:
            recommendation = (
                f"Your price is about {abs(pct):.1f}% above the market median. "
                "Only keep it if condition, rarity, grading, or availability justifies the premium."
            )
        else:
            recommendation = "Price looks broadly aligned with current references. Monitor but no urgent change."

    return ProductAnalysis(
        product=product,
        run_at=run_at,
        source_results=source_results,
        legit_market_prices=legit_prices,
        market_min_idr=market_min,
        market_median_idr=market_median,
        global_average_idr=global_average,
        price_delta_percent=price_delta_pct,
        alert_level=alert_level,
        underpriced_by_idr=underpriced_by,
        underpriced_by_percent=underpriced_pct,
        recommendation=recommendation,
    )
