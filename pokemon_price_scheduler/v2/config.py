from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pokemon_price_scheduler.domain.models import Product, Source

from .models import ConfigError, Stage


DEFAULT_SETTINGS: dict[str, Any] = {
    "min_own_price_idr": 500_000,
    "cheap_threshold_percent": 8,
    "alert_threshold_percent": 12,
    "comparable_min_ratio_to_own": 0.35,
    "comparable_max_ratio_to_own": 8,
    "tokopedia_scam_floor_ratio": 0.55,
    "tokopedia_min_legit_results": 3,
    "save_raw_snapshots": False,
    "max_snapshot_bytes": 750_000,
}


def load_validated_config(path: Path) -> tuple[dict[str, Any], list[Product]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(f"Config file not found: {path}", stage=Stage.LOAD_CONFIG) from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(f"Config JSON is invalid: {exc}", stage=Stage.LOAD_CONFIG) from exc

    if not isinstance(payload, dict):
        raise ConfigError("Config root must be a JSON object.", stage=Stage.LOAD_CONFIG)

    settings = dict(DEFAULT_SETTINGS)
    raw_settings = payload.get("settings", {})
    if raw_settings is None:
        raw_settings = {}
    if not isinstance(raw_settings, dict):
        raise ConfigError("settings must be an object.", stage=Stage.LOAD_CONFIG)
    settings.update(raw_settings)

    raw_products = payload.get("products")
    if not isinstance(raw_products, list):
        raise ConfigError("products must be a list.", stage=Stage.VALIDATE_PRODUCTS)

    products = [_load_product(item, index) for index, item in enumerate(raw_products)]
    return settings, products


def _load_product(item: Any, index: int) -> Product:
    if not isinstance(item, dict):
        raise ConfigError(f"products[{index}] must be an object.", stage=Stage.VALIDATE_PRODUCTS)

    title = _required_string(item, "title", index)
    own_price = _required_int(item, "own_price_idr", index)
    if own_price < 0:
        raise ConfigError(
            f"products[{index}].own_price_idr must be >= 0.",
            stage=Stage.VALIDATE_PRODUCTS,
        )

    raw_sources = item.get("sources", [])
    if raw_sources is None:
        raw_sources = []
    if not isinstance(raw_sources, list):
        raise ConfigError(f"products[{index}].sources must be a list.", stage=Stage.VALIDATE_PRODUCTS)

    sources = []
    for source_index, raw_source in enumerate(raw_sources):
        if not isinstance(raw_source, dict):
            raise ConfigError(
                f"products[{index}].sources[{source_index}] must be an object.",
                stage=Stage.VALIDATE_PRODUCTS,
            )
        url = str(raw_source.get("url", "")).strip()
        if not url:
            continue
        sources.append(
            Source(
                name=str(raw_source.get("name") or raw_source.get("kind") or "source"),
                kind=str(raw_source.get("kind") or "generic"),
                url=url,
            )
        )

    search_terms = item.get("search_terms", [])
    if search_terms is None:
        search_terms = []
    if not isinstance(search_terms, list):
        raise ConfigError(f"products[{index}].search_terms must be a list.", stage=Stage.VALIDATE_PRODUCTS)

    return Product(
        title=title,
        own_price_idr=own_price,
        tokopedia_url=str(item.get("tokopedia_url", "")).strip(),
        search_terms=[str(term).strip() for term in search_terms if str(term).strip()],
        sources=sources,
        status=str(item.get("status", "active") or "active"),
        sold_at=str(item.get("sold_at", "") or ""),
        added_at=str(item.get("added_at", "") or ""),
    )


def _required_string(item: dict[str, Any], key: str, index: int) -> str:
    value = item.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"products[{index}].{key} is required.", stage=Stage.VALIDATE_PRODUCTS)
    return value.strip()


def _required_int(item: dict[str, Any], key: str, index: int) -> int:
    value = item.get(key)
    if isinstance(value, bool):
        raise ConfigError(f"products[{index}].{key} must be an integer.", stage=Stage.VALIDATE_PRODUCTS)
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"products[{index}].{key} must be an integer.", stage=Stage.VALIDATE_PRODUCTS) from exc
