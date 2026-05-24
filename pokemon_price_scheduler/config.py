from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import Product, Source


DEFAULT_CONFIG = Path("config/products.json")


def load_config(path: Path = DEFAULT_CONFIG) -> tuple[dict[str, Any], list[Product]]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)

    settings = payload.get("settings", {})
    products = []
    for item in payload.get("products", []):
        sources = [
            Source(
                name=str(src.get("name", src.get("kind", "source"))),
                kind=str(src.get("kind", "generic")),
                url=str(src.get("url", "")),
            )
            for src in item.get("sources", [])
            if src.get("url")
        ]
        products.append(
            Product(
                title=str(item["title"]),
                own_price_idr=int(item["own_price_idr"]),
                tokopedia_url=str(item.get("tokopedia_url", "")),
                search_terms=[str(term) for term in item.get("search_terms", [])],
                sources=sources,
                status=str(item.get("status", "active")),
                sold_at=str(item.get("sold_at", "")),
                added_at=str(item.get("added_at", "")),
            )
        )
    return settings, products


def save_config(path: Path, settings: dict[str, Any], products: list[Product]) -> None:
    payload = {
        "settings": settings,
        "products": [
            {
                "title": p.title,
                "own_price_idr": p.own_price_idr,
                "tokopedia_url": p.tokopedia_url,
                "search_terms": p.search_terms,
                "sources": [
                    {"name": s.name, "kind": s.kind, "url": s.url}
                    for s in p.sources
                ],
                "status": p.status,
                "sold_at": p.sold_at,
                "added_at": p.added_at,
            }
            for p in products
        ],
    }
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
