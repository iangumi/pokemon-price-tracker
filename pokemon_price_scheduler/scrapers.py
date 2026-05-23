"""Backward-compatibility shim — re-exports from infrastructure layer."""

from .infrastructure.scrapers import (
    MarketplaceScraper,
    extract_store_products,
)

__all__ = ["MarketplaceScraper", "extract_store_products"]