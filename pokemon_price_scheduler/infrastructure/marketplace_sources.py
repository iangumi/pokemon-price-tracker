"""Runtime marketplace source construction for competitor discovery."""

from __future__ import annotations

import dataclasses as dc
from urllib.parse import quote, quote_plus

from pokemon_price_scheduler.domain.models import Product, Source


COMPETITOR_SEARCH_KINDS = frozenset({"tokopedia_find", "ebay_sold", "snkrdunk_search"})


def competitor_search_term(product: Product) -> str:
    """Return the broad user-controlled search term for competitor discovery."""
    for term in product.search_terms:
        clean = str(term).strip()
        if clean:
            return clean
    identity = product.card_identity
    return identity.tokopedia_query() or product.title


def build_competitor_sources(product: Product) -> list[Source]:
    term = competitor_search_term(product)
    tokopedia_path = quote(term.replace(" ", "-").lower())
    return [
        Source(
            name="tokopedia competitors",
            kind="tokopedia_find",
            url=f"https://www.tokopedia.com/find/{tokopedia_path}",
        ),
        Source(
            name="ebay sold",
            kind="ebay_sold",
            url=f"https://www.ebay.com/sch/i.html?_nkw={quote_plus(term)}&LH_Sold=1&LH_Complete=1",
        ),
        Source(
            name="snkrdunk search",
            kind="snkrdunk_search",
            url=(
                "https://snkrdunk.com/v3/search?func=all&refId=search"
                f"&keyword={quote_plus(term)}"
                "&sortKey=default&cardVersion=2&categoryIds=6&perPage=30&page=1"
            ),
        ),
    ]


def product_with_runtime_competitor_sources(product: Product) -> Product:
    """Replace stored marketplace search URLs with current search-term URLs."""
    custom_sources = [source for source in product.sources if source.kind not in COMPETITOR_SEARCH_KINDS]
    return dc.replace(product, sources=[*build_competitor_sources(product), *custom_sources])
