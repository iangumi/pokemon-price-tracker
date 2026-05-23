from __future__ import annotations

from typing import Any


def get_active_store_product_urls(settings: dict[str, Any]) -> set[str]:
    """Scrape the Tokopedia store listing page and return active product URLs.

    Reads the store URL from settings["tokopedia_store_url"].
    Uses the existing extract_store_products() parser from scrapers.py.
    """
    store_url = settings.get("tokopedia_store_url")
    if not store_url:
        return set()

    from .http import fetch_text
    from .scrapers import extract_store_products

    html = fetch_text(store_url)
    products = extract_store_products(html, min_price_idr=0)
    return {p["tokopedia_url"] for p in products if p.get("tokopedia_url")}


def get_active_store_product_urls_with_details(settings: dict[str, Any]) -> list[dict[str, Any]]:
    """Scrape the Tokopedia store listing page and return full product detail dicts.

    Returns list of {title, own_price_idr, tokopedia_url} for each active product.
    """
    store_url = settings.get("tokopedia_store_url")
    if not store_url:
        return []

    from .http import fetch_text
    from .scrapers import extract_store_products

    html = fetch_text(store_url)
    return extract_store_products(html, min_price_idr=0)