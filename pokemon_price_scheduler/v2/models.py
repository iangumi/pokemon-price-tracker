from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from pokemon_price_scheduler.domain.models import PriceObservation, Product, ProductAnalysis


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Stage(StrEnum):
    LOAD_CONFIG = "load_config"
    VALIDATE_PRODUCTS = "validate_products"
    DETECT_SOLD = "detect_sold"
    FETCH_SOURCES = "fetch_sources"
    PARSE_OBSERVATIONS = "parse_observations"
    ANALYZE_PRICES = "analyze_prices"
    PERSIST_RUN = "persist_run"
    RENDER_REPORTS = "render_reports"


class Severity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True)
class RunEvent:
    stage: str
    severity: str
    message: str
    product_id: str = ""
    product_slug: str = ""
    source_name: str = ""
    elapsed_ms: int | None = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FetchRecord:
    product_id: str
    product_slug: str
    source_name: str
    source_kind: str
    url: str
    status: str
    started_at: str
    elapsed_ms: int
    response_bytes: int = 0
    content_hash: str = ""
    artifact_path: str = ""
    error: str = ""
    fetch_backend: str = "stdlib"
    failure_kind: str = ""


@dataclass(frozen=True)
class ObservationDecision:
    product_id: str
    product_slug: str
    source_name: str
    source_kind: str
    url: str
    title: str
    raw_price: str
    price_idr: int
    relevance_score: float
    included: bool
    reason: str
    parser_strategy: str = "legacy_marketplace_scraper"

    @classmethod
    def from_observation(
        cls,
        product: Product,
        observation: PriceObservation,
        included: bool,
        reason: str,
    ) -> "ObservationDecision":
        return cls(
            product_id=product_id_for(product),
            product_slug=product.slug,
            source_name=observation.source_name,
            source_kind=observation.source_kind,
            url=observation.url,
            title=observation.title,
            raw_price=observation.raw_price,
            price_idr=observation.price_idr,
            relevance_score=observation.relevance_score,
            included=included,
            reason=reason,
        )


@dataclass(frozen=True)
class RunResult:
    run_id: int
    run_at: datetime
    analyses: list[ProductAnalysis]
    events: list[RunEvent]


class PipelineError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        stage: str,
        product_slug: str = "",
        source_name: str = "",
    ) -> None:
        super().__init__(message)
        self.stage = stage
        self.product_slug = product_slug
        self.source_name = source_name


class ConfigError(PipelineError):
    pass


class FetchError(PipelineError):
    pass


class AnalysisError(PipelineError):
    pass


def product_id_for(product: Product) -> str:
    if product.tokopedia_url:
        return product.tokopedia_url.rstrip("/").rsplit("/", 1)[-1].split("?", 1)[0] or product.slug
    return product.slug
