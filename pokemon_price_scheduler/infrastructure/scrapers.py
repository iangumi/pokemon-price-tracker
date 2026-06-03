"""Marketplace scrapers — infrastructure concern."""

from __future__ import annotations

import json
import re
from statistics import median
from typing import Any
from urllib.parse import quote_plus

from ..domain.models import PriceObservation, Source, SourceResult
from .http import fetch_text
from .parsing import (
    clean_text,
    extract_json_objects,
    likely_price_strings,
    parse_price_to_idr,
    reject_low_tokopedia_outliers,
    walk_json,
)


SNKRDUNK_API = "https://snkrdunk.com/v3/search"

# Pre-compiled regexes — compiled once at module load, reused across all scrape calls
_SNKRDUNK_SEARCH_RE = re.compile(r"func=all&refId=search")
_SSR_ITEM_RE = re.compile(
    r'<div[^>]+data-testid="divFindProduct#[^"]+"[^>]*>.*?'
    r'<a[^>]+href="(?P<url>[^"]+)"[^>]*>(?P<body>.*?)</a>\s*</div>',
    re.I | re.S,
)
_SSR_TITLE_RE = re.compile(r"<span[^>]*>(?P<title>[^<]{8,260})</span>", re.I | re.S)
_SSR_PRICE_RE = re.compile(r"Rp\s?[\d.]+", re.I)
_RAW_PRODUCT_RE = re.compile(
    r'"name":"(?P<title>(?:\\.|[^"])+)","product_url":"(?P<url>(?:\\.|[^"])+)".{0,1800}?'
    r'"price":\{"type":"id","generated":true,"id":"(?P<price_id>(?:\\.|[^"])+)"',
    re.S,
)
_STORE_RAW_PRODUCT_RE = re.compile(
    r'"name":"(?P<title>(?:\\.|[^"])+)","product_url":"(?P<url>(?:\\.|[^"])+)".{0,1800}?'
    r'"price":\{"type":"id","generated":true,"id":"(?P<price_id>(?:\\.|[^"])+)"',
    re.S,
)
_EBAY_ITEM_RE = re.compile(r'<li[^>]+class="[^"]*s-item[^"]*"[^>]*>(?P<body>.*?)</li>', re.I | re.S)
_EBAY_TITLE_RE = re.compile(r'<div[^>]+class="[^"]*s-item__title[^"]*"[^>]*>(?P<title>.*?)</div>', re.I | re.S)
_EBAY_PRICE_RE = re.compile(r'<span[^>]+class="[^"]*s-item__price[^"]*"[^>]*>(?P<price>.*?)</span>', re.I | re.S)
_EBAY_LINK_RE = re.compile(r'<a[^>]+class="[^"]*s-item__link[^"]*"[^>]+href="(?P<url>[^"]+)"', re.I | re.S)
_STORE_PRICE_REF_RE = re.compile(r'"text_idr":"(?P<price>Rp[\d.]+)"')
_STORE_FALLBACK_RE = re.compile(r"(?:Rp\s?[\d.]+(?:\s?(?:rb|ribu|jt|juta))?).{0,400}?([A-Z0-9][^<>]{10,120})", re.I | re.S)


def snkrdunk_search_url(keyword: str, page: int = 1) -> str:
    params = (
        f"func=all&refId=search"
        f"&keyword={quote_plus(keyword)}"
        f"&sortKey=default"
        f"&cardVersion=2"
        f"&categoryIds=6"
        f"&perPage=30"
        f"&page={page}"
    )
    return f"{SNKRDUNK_API}?{params}"


class MarketplaceScraper:
    def __init__(self, settings: dict[str, Any]):
        self.settings = settings

    def scrape(self, source: Source) -> SourceResult:
        try:
            if source.kind == "snkrdunk_api" or source.kind == "snkrdunk_search":
                if source.url.startswith("http"):
                    url = source.url
                else:
                    url = snkrdunk_search_url(source.url)
                html_text = fetch_text(url)
            else:
                html_text = fetch_text(source.url)
        except RuntimeError as exc:
            return SourceResult(source=source, warnings=[str(exc)])

        observations = self._extract_observations(source, html_text)
        warnings = []
        if not observations:
            warnings.append("No prices could be parsed. This source may require JavaScript, cookies, or a more specific URL.")

        if source.kind == "tokopedia_find" and observations:
            prices = [obs.price_idr for obs in observations]
            legit_prices = reject_low_tokopedia_outliers(
                prices,
                float(self.settings.get("tokopedia_scam_floor_ratio", 0.55)),
                int(self.settings.get("tokopedia_min_legit_results", 3)),
            )
            observations = [
                PriceObservation(
                    source_name=obs.source_name,
                    source_kind=obs.source_kind,
                    url=obs.url,
                    price_idr=obs.price_idr,
                    title=obs.title,
                    currency=obs.currency,
                    raw_price=obs.raw_price,
                    is_legit=obs.price_idr in legit_prices,
                )
                for obs in observations
            ]
            ignored = len(prices) - len([obs for obs in observations if obs.is_legit])
            if ignored:
                warnings.append(f"Ignored {ignored} low Tokopedia outlier(s) as likely scam/noise.")
        return SourceResult(source=source, observations=observations, warnings=warnings)

    def _extract_observations(self, source: Source, html_text: str) -> list[PriceObservation]:
        if source.kind == "tokopedia_find":
            tokopedia_items = extract_tokopedia_search_items(source, html_text)
            if tokopedia_items:
                return tokopedia_items[:30]
        if source.kind == "ebay_sold":
            ebay_items = extract_ebay_items(source, html_text)
            if ebay_items:
                return ebay_items[:30]
        if source.kind == "snkrdunk_api" or source.kind == "snkrdunk_search":
            snkrdunk_items = extract_snkrdunk_api(source, html_text)
            if snkrdunk_items:
                return snkrdunk_items[:30]

        observations: list[PriceObservation] = []
        seen: set[tuple[str, int]] = set()

        for obj in extract_json_objects(html_text):
            for node in walk_json(obj):
                if not isinstance(node, dict):
                    continue
                title = self._title_from_node(node)
                price = self._price_from_node(node)
                url = str(node.get("url") or node.get("productUrl") or source.url)
                if price is None:
                    continue
                key = (title or source.name, price)
                if key in seen:
                    continue
                seen.add(key)
                observations.append(
                    PriceObservation(
                        source_name=source.name,
                        source_kind=source.kind,
                        url=url,
                        price_idr=price,
                        title=title,
                        raw_price=str(price),
                    )
                )

        if observations:
            return observations[:30]

        for price_text in likely_price_strings(html_text):
            price = parse_price_to_idr(price_text)
            if price is None:
                continue
            key = (source.name, price)
            if key in seen:
                continue
            seen.add(key)
            observations.append(
                PriceObservation(
                    source_name=source.name,
                    source_kind=source.kind,
                    url=source.url,
                    price_idr=price,
                    raw_price=price_text,
                )
            )
        return observations[:30]

    def _title_from_node(self, node: dict[str, Any]) -> str:
        for key in ("name", "title", "productName", "itemName"):
            value = node.get(key)
            if isinstance(value, str) and len(value) > 2:
                return clean_text(value)
        return ""

    def _price_from_node(self, node: dict[str, Any]) -> int | None:
        for key in ("price", "lowPrice", "highPrice", "priceAmount", "originalPrice"):
            if key not in node:
                continue
            value = node[key]
            if isinstance(value, (int, float)):
                return int(value)
            if isinstance(value, str):
                parsed = parse_price_to_idr(value)
                if parsed is not None:
                    return parsed
        offers = node.get("offers")
        if isinstance(offers, dict):
            return self._price_from_node(offers)
        if isinstance(offers, list):
            prices = [self._price_from_node(item) for item in offers if isinstance(item, dict)]
            prices = [price for price in prices if price is not None]
            if prices:
                return int(median(prices))
        return None


def extract_tokopedia_search_items(source: Source, html_text: str) -> list[PriceObservation]:
    items: list[PriceObservation] = []
    seen: set[tuple[str, int]] = set()
    for match in _SSR_ITEM_RE.finditer(html_text):
        body = match.group("body")
        title_match = _SSR_TITLE_RE.search(body)
        price_match = _SSR_PRICE_RE.search(body)
        if not title_match or not price_match:
            continue
        title = clean_text(title_match.group("title"))
        price = parse_price_to_idr(price_match.group(0))
        if price is None:
            continue
        url = clean_text(match.group("url"))
        key = (title, price)
        if key in seen:
            continue
        seen.add(key)
        items.append(
            PriceObservation(
                source_name=source.name,
                source_kind=source.kind,
                url=url,
                price_idr=price,
                title=title,
                raw_price=price_match.group(0),
            )
        )
    if items:
        return items

    for match in _RAW_PRODUCT_RE.finditer(html_text):
        title = decode_jsonish(match.group("title"))
        url = decode_jsonish(match.group("url"))
        price_id = match.group("price_id")
        price_match = re.search(re.escape(price_id) + r'":\{"text_idr":"(?P<price>Rp[\d.]+)"', html_text)
        if not price_match:
            continue
        price = parse_price_to_idr(price_match.group("price"))
        if price is None:
            continue
        key = (title, price)
        if key in seen:
            continue
        seen.add(key)
        items.append(
            PriceObservation(
                source_name=source.name,
                source_kind=source.kind,
                url=url,
                price_idr=price,
                title=title,
                raw_price=price_match.group("price"),
            )
        )
    return items


def extract_ebay_items(source: Source, html_text: str) -> list[PriceObservation]:
    items: list[PriceObservation] = []
    seen: set[tuple[str, int]] = set()
    for match in _EBAY_ITEM_RE.finditer(html_text):
        body = match.group("body")
        title_match = _EBAY_TITLE_RE.search(body)
        price_match = _EBAY_PRICE_RE.search(body)
        link_match = _EBAY_LINK_RE.search(body)
        if not title_match or not price_match:
            continue
        title = clean_text(re.sub(r"<[^>]+>", " ", title_match.group("title")))
        raw_price = clean_text(re.sub(r"<[^>]+>", " ", price_match.group("price")))
        price = parse_price_to_idr(raw_price)
        if price is None:
            continue
        url = clean_text(link_match.group("url")) if link_match else source.url
        key = (title, price)
        if key in seen:
            continue
        seen.add(key)
        items.append(
            PriceObservation(
                source_name=source.name,
                source_kind=source.kind,
                url=url,
                price_idr=price,
                title=title,
                raw_price=raw_price,
                currency="USD",
            )
        )
    return items


def decode_jsonish(value: str) -> str:
    try:
        return json.loads(f'"{value}"')
    except json.JSONDecodeError:
        return clean_text(value)


def extract_snkrdunk_api(source: Source, raw_text: str) -> list[PriceObservation]:
    items: list[PriceObservation] = []
    seen: set[tuple[str, int]] = set()

    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError:
        return []

    def walk(data):
        if isinstance(data, dict):
            products = data.get("products") or data.get("items")
            if isinstance(products, list) and products:
                for product in products:
                    if not isinstance(product, dict):
                        continue
                    title = clean_text(product.get("title", "") or product.get("name", ""))
                    price_val = product.get("salePrice") or product.get("price") or product.get("priceInt")
                    if not title or not price_val:
                        continue
                    if isinstance(price_val, str):
                        price = parse_price_to_idr(price_val)
                    else:
                        price = int(price_val) if price_val else 0
                    if price is None or price == 0:
                        continue
                    link = product.get("link") or product.get("url") or ""
                    if link and not link.startswith("http"):
                        link = "https://snkrdunk.com" + link
                    key = (title, price)
                    if key in seen:
                        continue
                    seen.add(key)
                    items.append(
                        PriceObservation(
                            source_name=source.name,
                            source_kind=source.kind,
                            url=link or source.url,
                            price_idr=price,
                            title=title,
                            raw_price=str(price_val),
                            currency="JPY",
                        )
                    )
                return
            for value in data.values():
                walk(value)
        elif isinstance(data, list):
            for item in data:
                walk(item)

    walk(data)
    return items


def extract_store_products(html_text: str, min_price_idr: int) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()

    for match in _STORE_RAW_PRODUCT_RE.finditer(html_text):
        title = decode_jsonish(match.group("title"))
        url = decode_jsonish(match.group("url"))
        price_id = match.group("price_id")
        price_match = _STORE_PRICE_REF_RE.search(html_text)
        if not price_match:
            continue
        price = parse_price_to_idr(price_match.group("price"))
        if price is None or price < min_price_idr:
            continue
        key = (title, price)
        if key in seen:
            continue
        seen.add(key)
        found.append({"title": title, "own_price_idr": price, "tokopedia_url": url})
    if found:
        return found

    for obj in extract_json_objects(html_text):
        normalized_cache: dict[str, Any] = {}
        for cache_candidate in walk_json(obj):
            if not isinstance(cache_candidate, dict):
                continue
            for key, value in cache_candidate.items():
                if isinstance(key, str) and isinstance(value, dict):
                    normalized_cache[key] = value
        for node in walk_json(obj):
            if not isinstance(node, dict):
                continue
            title = ""
            for key in ("name", "title", "productName"):
                if isinstance(node.get(key), str):
                    title = clean_text(node[key])
                    break
            if not title:
                continue
            price = None
            price_ref = node.get("price")
            if isinstance(price_ref, dict) and isinstance(price_ref.get("id"), str):
                price_node = normalized_cache.get(price_ref["id"])
                if isinstance(price_node, dict):
                    for key in ("text_idr", "text", "price", "priceAmount"):
                        if key in price_node:
                            price = parse_price_to_idr(str(price_node[key]))
                            if price is not None:
                                break
            for key in ("price", "priceInt", "priceAmount", "minPrice"):
                if price is not None:
                    break
                if key in node:
                    price = parse_price_to_idr(str(node[key]))
                    if price is not None:
                        break
            if price is None or price < min_price_idr:
                continue
            url = str(node.get("url") or node.get("productUrl") or node.get("product_url") or "")
            key = (title, price)
            if key in seen:
                continue
            seen.add(key)
            found.append({"title": title, "own_price_idr": price, "tokopedia_url": url})

    if found:
        return found

    for match in _STORE_FALLBACK_RE.finditer(html_text):
        price_text = match.group(0).split("<", 1)[0]
        price = parse_price_to_idr(price_text)
        title = clean_text(match.group(1))
        if title.startswith(("div class", "typename")):
            continue
        if price is None or price < min_price_idr:
            continue
        key = (title, price)
        if key in seen:
            continue
        seen.add(key)
        found.append({"title": title, "own_price_idr": price, "tokopedia_url": ""})
    return found
