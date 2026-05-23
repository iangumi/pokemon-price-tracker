"""Text extraction and price-parsing utilities — infrastructure concern."""

from __future__ import annotations

import json
import re
from statistics import median
from typing import Any

from ..domain.text import clean_text

USD_TO_IDR = 16000


def parse_price_to_idr(value: str) -> int | None:
    text = clean_text(value).lower()
    if not text:
        return None
    multiplier = 1
    if "usd" in text or "us $" in text or "$" in text:
        multiplier = USD_TO_IDR
    number_match = re.search(r"(\d[\d.,]*)", text)
    if not number_match:
        return None
    raw = number_match.group(1)
    if multiplier == USD_TO_IDR:
        normalized = raw.replace(",", "")
        try:
            return round(float(normalized) * multiplier)
        except ValueError:
            return None
    digits = re.sub(r"\D", "", raw)
    if not digits:
        return None
    amount = int(digits)
    if "jt" in text or "juta" in text:
        amount *= 1_000_000
    elif "rb" in text or "ribu" in text:
        amount *= 1_000
    return amount


def extract_json_objects(html_text: str) -> list[Any]:
    objects: list[Any] = []
    for match in re.finditer(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', html_text, re.I | re.S):
        raw = html.unescape(match.group(1)).strip()
        if not raw:
            continue
        try:
            objects.append(json.loads(raw))
        except json.JSONDecodeError:
            continue

    next_data = re.search(r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>', html_text, re.I | re.S)
    if next_data:
        try:
            objects.append(json.loads(html.unescape(next_data.group(1))))
        except json.JSONDecodeError:
            pass
    return objects


def walk_json(value: Any):
    yield value
    if isinstance(value, dict):
        for child in value.values():
            yield from walk_json(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_json(child)


def likely_price_strings(html_text: str) -> list[str]:
    candidates = set()
    patterns = [
        r"Rp\s?[\d.]+(?:\s?(?:rb|ribu|jt|juta))?",
        r"US\s?\$[\d,.]+",
        r"\$[\d,.]+",
        r"IDR\s?[\d,.]+",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, html_text, re.I):
            candidates.add(clean_text(match.group(0)))
    return list(candidates)


def reject_low_tokopedia_outliers(prices: list[int], floor_ratio: float, min_results: int) -> set[int]:
    if len(prices) < min_results:
        return set(prices)
    med = median(prices)
    floor = med * floor_ratio
    return {price for price in prices if price >= floor}