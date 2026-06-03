from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from pokemon_price_scheduler.domain.analysis import analyze_product
from pokemon_price_scheduler.domain.models import Product, Source, SourceResult
from pokemon_price_scheduler.infrastructure.http import classify_fetch_error, fetch_text, resolve_fetch_backend
from pokemon_price_scheduler.infrastructure.scrapers import MarketplaceScraper
from pokemon_price_scheduler.store_sync import get_active_store_product_urls

from .config import load_validated_config
from .models import (
    FetchRecord,
    ObservationDecision,
    PipelineError,
    RunEvent,
    RunResult,
    Severity,
    Stage,
    product_id_for,
    utc_now,
)
from .reports import DebugReportWriter
from .storage import TraceStore


class Fetcher(Protocol):
    def __call__(self, url: str, timeout: int = 30, backend: str = "auto") -> str:
        ...


@dataclass(frozen=True)
class PipelineOptions:
    config_path: Path = Path("config/products.json")
    db_path: Path = Path("data/price_history.sqlite3")
    report_dir: Path = Path("reports")
    artifact_dir: Path = Path("data/runs")
    limit: int | None = None
    min_price_idr: int | None = None
    ai_summary: bool = False
    debug: bool = False
    detect_sold: bool = True
    render_reports: bool = True
    fetch_backend: str = "auto"


class RunPipeline:
    def __init__(
        self,
        options: PipelineOptions,
        *,
        fetcher: Fetcher = fetch_text,
        store: TraceStore | None = None,
        report_writer: DebugReportWriter | None = None,
    ) -> None:
        self.options = options
        self.fetcher = fetcher
        self.store = store or TraceStore(options.db_path)
        self.report_writer = report_writer or DebugReportWriter(options.report_dir)
        self.events: list[RunEvent] = []
        self.fetch_records: list[FetchRecord] = []
        self.decisions: list[ObservationDecision] = []
        self._current_product: Product | None = None
        self._current_source: Source | None = None
        self._trace_persisted = False

    def run(self) -> RunResult:
        run_at = utc_now()
        settings, products = self._timed(Stage.LOAD_CONFIG, lambda: load_validated_config(self.options.config_path))
        run_id = self.store.create_run(
            run_at.isoformat(),
            {
                "settings": settings,
                "config_path": str(self.options.config_path),
                "limit": self.options.limit,
                "min_price_idr": self.options.min_price_idr,
                "debug": self.options.debug,
                "fetch_backend": self.options.fetch_backend,
            },
        )

        try:
            products = self._prepare_products(settings, products)
            analyses = self._run_products(run_id, settings, products, run_at)
            self._timed(Stage.PERSIST_RUN, lambda: self._persist(run_id, analyses))
            if self.options.render_reports:
                self._timed(Stage.RENDER_REPORTS, lambda: self.report_writer.write(analyses, run_id))
            self._event(Stage.RENDER_REPORTS, Severity.INFO, f"Run {run_id} complete.")
            self.store.add_events(run_id, self.events)
            self.store.finish_run(run_id, "complete")
            return RunResult(run_id=run_id, run_at=run_at, analyses=analyses, events=self.events)
        except Exception as exc:
            if isinstance(exc, PipelineError):
                self._event(exc.stage, Severity.ERROR, str(exc), product_slug=exc.product_slug, source_name=exc.source_name)
            else:
                self._event("unknown", Severity.ERROR, f"{type(exc).__name__}: {exc}")
            self.store.add_events(run_id, self.events)
            if not self._trace_persisted:
                self.store.add_fetch_records(run_id, self.fetch_records)
                self.store.add_observation_decisions(run_id, self.decisions)
            self.store.finish_run(run_id, "failed")
            raise

    def _prepare_products(self, settings: dict, products: list[Product]) -> list[Product]:
        def prepare() -> list[Product]:
            active_products = [product for product in products if product.status != "sold"]
            if self.options.detect_sold:
                active_urls = get_active_store_product_urls(settings)
                if active_urls:
                    active_products = [
                        product
                        for product in active_products
                        if not product.tokopedia_url or product.tokopedia_url in active_urls
                    ]
                    self._event(
                        Stage.DETECT_SOLD,
                        Severity.INFO,
                        f"Detected {len(active_products)} active products from store page.",
                    )
            min_price = self.options.min_price_idr
            if min_price is None:
                min_price = int(settings.get("min_own_price_idr", 500_000))
            filtered = [product for product in active_products if product.own_price_idr >= min_price]
            if self.options.limit is not None:
                filtered = filtered[: self.options.limit]
            self._event(
                Stage.VALIDATE_PRODUCTS,
                Severity.INFO,
                f"Selected {len(filtered)} product(s) for analysis.",
                details={"configured": len(products), "active": len(active_products), "min_price_idr": min_price},
            )
            return filtered

        return self._timed(Stage.VALIDATE_PRODUCTS, prepare)

    def _run_products(
        self,
        run_id: int,
        settings: dict,
        products: list[Product],
        run_at,
    ) -> list:
        scraper = MarketplaceScraper(settings)
        scraper_fetcher = self._make_traced_fetcher(run_id)
        analyses = []
        original_fetch = _patch_scraper_fetch(scraper_fetcher)
        try:
            for product in products:
                source_results = []
                for source in product.sources:
                    result = self._scrape_source(scraper, product, source)
                    source_results.append(result)
                analysis = self._timed(
                    Stage.ANALYZE_PRICES,
                    lambda product=product, source_results=source_results: analyze_product(
                        product,
                        source_results,
                        run_at,
                        settings,
                    ),
                    product=product,
                )
                self.decisions.extend(_decisions_for_analysis(product, analysis, settings))
                analyses.append(analysis)
        finally:
            _restore_scraper_fetch(original_fetch)

        if self.options.ai_summary:
            from pokemon_price_scheduler.infrastructure.ai import attach_ai_summaries

            analyses, warnings = attach_ai_summaries(analyses)
            for warning in warnings:
                self._event(Stage.ANALYZE_PRICES, Severity.WARNING, warning)
        return analyses

    def _scrape_source(self, scraper: MarketplaceScraper, product: Product, source: Source) -> SourceResult:
        self._current_product = product
        self._current_source = source
        try:
            return self._timed(
                Stage.PARSE_OBSERVATIONS,
                lambda: scraper.scrape(source),
                product=product,
                source=source,
            )
        finally:
            self._current_product = None
            self._current_source = None

    def _make_traced_fetcher(self, run_id: int) -> Fetcher:
        def traced_fetch(url: str, timeout: int = 30) -> str:
            started = utc_now()
            start = time.monotonic()
            product = self._current_product
            source = self._current_source
            backend = resolve_fetch_backend(url, self.options.fetch_backend)
            try:
                try:
                    text = self.fetcher(url, timeout=timeout, backend=self.options.fetch_backend)
                except TypeError:
                    text = self.fetcher(url, timeout=timeout)
                elapsed_ms = int((time.monotonic() - start) * 1000)
                artifact_path = self._write_snapshot(run_id, url, text)
                self.fetch_records.append(
                    FetchRecord(
                        product_id=product_id_for(product) if product else "",
                        product_slug=product.slug if product else "",
                        source_name=source.name if source else "",
                        source_kind=source.kind if source else "",
                        url=url,
                        status="ok",
                        started_at=started.isoformat(),
                        elapsed_ms=elapsed_ms,
                        response_bytes=len(text.encode("utf-8", errors="replace")),
                        content_hash=hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest(),
                        artifact_path=artifact_path,
                        fetch_backend=backend,
                    )
                )
                return text
            except Exception as exc:
                elapsed_ms = int((time.monotonic() - start) * 1000)
                self.fetch_records.append(
                    FetchRecord(
                        product_id=product_id_for(product) if product else "",
                        product_slug=product.slug if product else "",
                        source_name=source.name if source else "",
                        source_kind=source.kind if source else "",
                        url=url,
                        status="error",
                        started_at=started.isoformat(),
                        elapsed_ms=elapsed_ms,
                        error=str(exc),
                        fetch_backend=backend,
                        failure_kind=classify_fetch_error(exc),
                    )
                )
                raise

        return traced_fetch

    def _write_snapshot(self, run_id: int, url: str, text: str) -> str:
        if not self.options.debug:
            return ""
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
        run_dir = self.options.artifact_dir / str(run_id) / "sources"
        run_dir.mkdir(parents=True, exist_ok=True)
        max_bytes = 750_000
        path = run_dir / f"{digest}.html"
        encoded = text.encode("utf-8", errors="replace")[:max_bytes]
        path.write_bytes(encoded)
        return str(path)

    def _persist(self, run_id: int, analyses: list) -> None:
        self.store.add_fetch_records(run_id, self.fetch_records)
        self.store.add_observation_decisions(run_id, self.decisions)
        self._trace_persisted = True
        self.store.save_results(run_id, analyses)

    def _timed(self, stage: str, func, *, product: Product | None = None, source: Source | None = None):
        start = time.monotonic()
        try:
            result = func()
        except Exception as exc:
            elapsed_ms = int((time.monotonic() - start) * 1000)
            self._event(
                stage,
                Severity.ERROR,
                str(exc),
                product_id=product_id_for(product) if product else "",
                product_slug=product.slug if product else "",
                source_name=source.name if source else "",
                elapsed_ms=elapsed_ms,
            )
            raise
        elapsed_ms = int((time.monotonic() - start) * 1000)
        self._event(
            stage,
            Severity.INFO,
            f"{stage} completed.",
            product_id=product_id_for(product) if product else "",
            product_slug=product.slug if product else "",
            source_name=source.name if source else "",
            elapsed_ms=elapsed_ms,
        )
        return result

    def _event(
        self,
        stage: str,
        severity: str,
        message: str,
        *,
        product_id: str = "",
        product_slug: str = "",
        source_name: str = "",
        elapsed_ms: int | None = None,
        details: dict | None = None,
    ) -> None:
        self.events.append(
            RunEvent(
                stage=str(stage),
                severity=str(severity),
                message=message,
                product_id=product_id,
                product_slug=product_slug,
                source_name=source_name,
                elapsed_ms=elapsed_ms,
                details=details or {},
            )
        )


def _decisions_for_analysis(product: Product, analysis, settings: dict) -> list[ObservationDecision]:
    min_ratio = float(settings.get("comparable_min_ratio_to_own", 0.35))
    max_ratio = float(settings.get("comparable_max_ratio_to_own", 8))
    low_bound = product.own_price_idr * min_ratio
    high_bound = product.own_price_idr * max_ratio
    decisions: list[ObservationDecision] = []
    for source_result in analysis.source_results:
        for observation in source_result.observations:
            included = observation.price_idr in analysis.legit_market_prices and observation.is_legit
            if included:
                reason = "included"
            elif not observation.is_legit:
                reason = "source_marked_outlier"
            elif observation.price_idr < low_bound:
                reason = "below_comparable_min_ratio"
            elif observation.price_idr > high_bound:
                reason = "above_comparable_max_ratio"
            else:
                reason = "excluded_duplicate_or_unselected"
            decisions.append(ObservationDecision.from_observation(product, observation, included, reason))
    return decisions


def _patch_scraper_fetch(fetcher: Fetcher):
    import pokemon_price_scheduler.infrastructure.scrapers as scrapers

    original = scrapers.fetch_text
    scrapers.fetch_text = fetcher
    return original


def _restore_scraper_fetch(original) -> None:
    import pokemon_price_scheduler.infrastructure.scrapers as scrapers

    scrapers.fetch_text = original
