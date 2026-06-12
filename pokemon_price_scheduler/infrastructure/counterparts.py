"""Counterpart candidate helpers and deterministic currency conversion."""

from __future__ import annotations

import re
from typing import Any

from pokemon_price_scheduler.domain.models import Product
from pokemon_price_scheduler.domain.text import clean_text


FX_RATES_TO_IDR = {
    "IDR": 1.0,
    "USD": 16_000.0,
    "JPY": 110.0,
}


def convert_to_idr(amount: float | int | None, currency: str) -> tuple[int | None, float | None]:
    currency = normalize_currency(currency)
    rate = FX_RATES_TO_IDR.get(currency)
    if amount is None or rate is None:
        return None, rate
    return round(float(amount) * rate), rate


def normalize_currency(currency: str | None) -> str:
    value = (currency or "IDR").upper()
    if value in {"US$", "$"}:
        return "USD"
    if value in {"¥", "YEN"}:
        return "JPY"
    return value if value in FX_RATES_TO_IDR else "IDR"


def infer_currency(source_kind: str, raw_price: str = "") -> str:
    text = raw_price.lower()
    if "usd" in text or "us $" in text or "$" in text:
        return "USD"
    if "jpy" in text or "¥" in text or source_kind in {"snkrdunk_search", "snkrdunk_api", "yuyutei", "mercari_jp"}:
        return "JPY"
    if source_kind == "ebay_sold":
        return "USD"
    return "IDR"


def raw_amount_from_price(raw_price: str, fallback_idr: int | None, currency: str) -> float | None:
    match = re.search(r"(\d[\d,.]*)", raw_price or "")
    if match:
        raw = match.group(1)
        if currency in {"USD", "JPY"}:
            try:
                return float(raw.replace(",", ""))
            except ValueError:
                return None
        digits = re.sub(r"\D", "", raw)
        return float(digits) if digits else None
    if fallback_idr is None:
        return None
    if currency == "IDR":
        return float(fallback_idr)
    rate = FX_RATES_TO_IDR.get(currency)
    return round(float(fallback_idr) / rate, 2) if rate else None


def build_counterpart_candidates(product: Product, observations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for observation in observations:
        source_kind = str(observation.get("source_kind") or "")
        title = clean_text(str(observation.get("title") or ""))
        if not title:
            continue
        currency = infer_currency(source_kind, str(observation.get("raw_price") or ""))
        raw_amount = raw_amount_from_price(
            str(observation.get("raw_price") or ""),
            int(observation["price_idr"]) if observation.get("price_idr") is not None else None,
            currency,
        )
        converted, rate = convert_to_idr(raw_amount, currency)
        if converted is None:
            continue
        confidence, reason = counterpart_confidence(product, title, float(observation.get("relevance_score") or 0))
        candidates.append(
            {
                "source_name": str(observation.get("source_name") or source_kind or "source"),
                "source_kind": source_kind,
                "source_url": str(observation.get("url") or ""),
                "title": title,
                "language": infer_language(title),
                "version": infer_version(title),
                "raw_price": format_raw_price(raw_amount, currency),
                "currency": currency,
                "converted_price_idr": converted,
                "fx_rate_to_idr": rate,
                "confidence": confidence,
                "match_reason": reason,
            }
        )
    return sorted(candidates, key=lambda item: (-float(item["confidence"]), int(item["converted_price_idr"])))[:20]


def counterpart_confidence(product: Product, title: str, relevance_score: float = 0) -> tuple[float, str]:
    identity = product.card_identity
    title_lower = title.lower()
    reasons = []
    score = max(0.0, min(100.0, relevance_score))
    if identity.name and identity.name.lower() in title_lower:
        score += 25
        reasons.append("name match")
    if identity.card_number and identity.card_number.lower() in title_lower:
        score += 30
        reasons.append("card number match")
    if identity.set_symbol and identity.set_symbol.lower() in title_lower:
        score += 20
        reasons.append("set symbol match")
    if identity.rarity and re.search(rf"\b{re.escape(identity.rarity.lower())}\b", title_lower):
        score += 10
        reasons.append("rarity match")
    if not reasons:
        own_terms = {term for term in re.split(r"\W+", identity.name.lower()) if len(term) > 2}
        title_terms = {term for term in re.split(r"\W+", title_lower) if len(term) > 2}
        overlap = len(own_terms & title_terms)
        if overlap:
            score += min(20, overlap * 5)
            reasons.append("name word overlap")
    return round(min(score, 100.0), 1), ", ".join(reasons) or "weak title match"


def infer_language(title: str) -> str:
    lower = f" {title.lower()} "
    if any(marker in lower for marker in (" japanese ", " jp ", " jpn ", " japan ")):
        return "Japanese"
    if any(marker in lower for marker in (" english ", " eng ", " en ")):
        return "English"
    return "Unknown"


def infer_version(title: str) -> str:
    lower = title.lower()
    if any(token in lower for token in ("elite trainer box", " etb ", "booster box", "sealed")):
        return "sealed"
    if any(token in lower for token in ("psa", "bgs", "cgc")):
        return "graded"
    return "single"


def format_raw_price(amount: float | None, currency: str) -> str:
    if amount is None:
        return "-"
    if currency == "USD":
        return f"USD {amount:,.2f}"
    if currency == "JPY":
        return f"JPY {amount:,.0f}"
    return f"IDR {amount:,.0f}"
