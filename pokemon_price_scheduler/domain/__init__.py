"""Domain layer — pure business logic, no I/O dependencies."""

from .models import (
    Product,
    Source,
    PriceObservation,
    SourceResult,
    ProductAnalysis,
    alert_label,
    utc_now,
)
from .analysis import analyze_product, score_observations, relevance_score
from .card_parser import CardIdentity, parse_card_identity

__all__ = [
    "Product",
    "Source",
    "PriceObservation",
    "SourceResult",
    "ProductAnalysis",
    "alert_label",
    "utc_now",
    "analyze_product",
    "score_observations",
    "relevance_score",
    "CardIdentity",
    "parse_card_identity",
]