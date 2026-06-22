"""Deterministic currency conversion helpers for marketplace evidence."""

from __future__ import annotations


FX_RATES_TO_IDR = {
    "IDR": 1.0,
    "USD": 16_000.0,
    "JPY": 110.0,
}


def normalize_currency(currency: str | None) -> str:
    value = (currency or "IDR").upper()
    if value in {"US$", "$"}:
        return "USD"
    if value in {"¥", "YEN"}:
        return "JPY"
    return value if value in FX_RATES_TO_IDR else "IDR"


def convert_to_idr(amount: float | int | None, currency: str) -> tuple[int | None, float | None]:
    currency = normalize_currency(currency)
    rate = FX_RATES_TO_IDR.get(currency)
    if amount is None or rate is None:
        return None, rate
    return round(float(amount) * rate), rate


def default_currency_for_source(source_kind: str, currency: str | None = None) -> str:
    normalized = normalize_currency(currency)
    if currency:
        return normalized
    if source_kind in {"snkrdunk_search", "snkrdunk_api", "yuyutei", "mercari_jp"}:
        return "JPY"
    if source_kind == "ebay_sold":
        return "USD"
    return "IDR"
