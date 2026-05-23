from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .card_parser import CardIdentity, parse_card_identity


@dataclass(frozen=True)
class Source:
    name: str
    kind: str
    url: str


@dataclass(frozen=True)
class Product:
    title: str
    own_price_idr: int
    tokopedia_url: str = ""
    search_terms: list[str] = field(default_factory=list)
    sources: list[Source] = field(default_factory=list)
    status: str = "active"
    sold_at: str = ""
    added_at: str = ""

    @property
    def slug(self) -> str:
        identity = self.card_identity
        parts = [identity.name, identity.rarity, identity.set_symbol,
                 identity.card_number, identity.condition]
        slug = "-".join(p.lower().replace(" ", "-") for p in parts if p)
        import re
        slug = re.sub(r"[^a-z0-9-]", "", slug)
        slug = re.sub(r"-+", "-", slug).strip("-")[:90]
        return slug or "product"

    @property
    def language(self) -> str:
        return self.card_identity.language

    @property
    def card_identity(self) -> CardIdentity:
        return parse_card_identity(self.title)


@dataclass(frozen=True)
class PriceObservation:
    source_name: str
    source_kind: str
    url: str
    price_idr: int
    title: str = ""
    currency: str = "IDR"
    raw_price: str = ""
    is_legit: bool = True
    relevance_score: float = 0


@dataclass(frozen=True)
class SourceResult:
    source: Source
    observations: list[PriceObservation] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ProductAnalysis:
    product: Product
    run_at: datetime
    source_results: list[SourceResult]
    legit_market_prices: list[int]
    market_min_idr: int | None
    market_median_idr: int | None
    global_average_idr: int | None
    price_delta_percent: float | None
    alert_level: str
    underpriced_by_idr: int | None
    underpriced_by_percent: float | None
    recommendation: str
    ai_summary: str = ""

    def to_row(self) -> dict[str, Any]:
        return {
            "run_at": self.run_at.isoformat(),
            "title": self.product.title,
            "language": self.product.language,
            "own_price_idr": self.product.own_price_idr,
            "market_min_idr": self.market_min_idr,
            "market_median_idr": self.market_median_idr,
            "global_average_idr": self.global_average_idr,
            "price_delta_percent": self.price_delta_percent,
            "alert_level": self.alert_level,
            "underpriced_by_idr": self.underpriced_by_idr,
            "underpriced_by_percent": self.underpriced_by_percent,
            "recommendation": self.recommendation,
            "ai_summary": self.ai_summary,
        }


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def alert_label(level: str) -> str:
    """Map alert level to a human-readable label."""
    return {"red": "Price too high", "amber": "Price a bit high", "none": ""}.get(level, level)