"""Composable report engine — infrastructure concern."""

from __future__ import annotations

import csv
from abc import ABC, abstractmethod
from pathlib import Path

from pokemon_price_scheduler.domain.models import ProductAnalysis


REPORT_DIR = Path("reports")
CHART_DIR = REPORT_DIR / "charts"


class Report(ABC):
    """Abstract base for all report generators."""

    @abstractmethod
    def render(self, analyses: list[ProductAnalysis], run_id: int) -> None:
        """Render the report to its destination."""


class MarkdownReport(Report):
    """Writes a human-readable markdown summary of all analyses."""

    def render(self, analyses: list[ProductAnalysis], run_id: int) -> None:
        path = REPORT_DIR / "latest.md"
        idr_val = lambda v: f"Rp {v:,.0f}".replace(",", ".") if v else "-"
        lines = [f"# Pokemon Price Report - Run {run_id}", ""]
        if analyses:
            lines.append(f"Generated: {analyses[0].run_at.isoformat()}")
            lines.append("")

        underpriced = [a for a in analyses if a.underpriced_by_idr]
        lines.append("## Priority Changes")
        lines.append("")
        if not underpriced:
            lines.append("No clearly underpriced cards found from parsed sources.")
        else:
            for analysis in sorted(underpriced, key=lambda item: item.underpriced_by_idr or 0, reverse=True):
                lines.extend(self._card_block(analysis, idr_val))

        lines.extend(["", "## All Products", ""])
        for analysis in analyses:
            lines.extend(self._card_block(analysis, idr_val))
        path.write_text("\n".join(lines), encoding="utf-8")

    def _card_block(self, analysis: ProductAnalysis, idr_val) -> list[str]:
        from pokemon_price_scheduler.domain.models import alert_label
        return [
            f"### {analysis.product.title}",
            f"- Language: {analysis.product.language}",
            f"- Your price: {idr_val(analysis.product.own_price_idr)}",
            f"- Market median: {idr_val(analysis.market_median_idr)}",
            f"- Underpriced by: {idr_val(analysis.underpriced_by_idr)} ({analysis.underpriced_by_percent}%)",
            f"- Recommendation: {analysis.recommendation}",
            *([f"- AI note: {analysis.ai_summary}"] if analysis.ai_summary else []),
            f"- Chart: charts/{analysis.product.slug}.svg",
            "",
        ]


class CSVReport(Report):
    """Writes a flat CSV of all product analyses."""

    def render(self, analyses: list[ProductAnalysis], run_id: int) -> None:
        path = REPORT_DIR / "latest.csv"
        fieldnames = [
            "run_at", "title", "language", "own_price_idr",
            "market_min_idr", "market_median_idr", "global_average_idr",
            "price_delta_percent", "alert_level",
            "underpriced_by_idr", "underpriced_by_percent",
            "recommendation", "ai_summary",
        ]
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for analysis in analyses:
                writer.writerow(analysis.to_row())


class SVGSummaryReport(Report):
    """Writes sparkline SVG price-history charts for each product."""

    def render(self, analyses: list[ProductAnalysis], run_id: int) -> None:
        CHART_DIR.mkdir(parents=True, exist_ok=True)
        for analysis in analyses:
            self._write_chart(analysis.product.slug, CHART_DIR / f"{analysis.product.slug}.svg")

    def _write_chart(self, slug: str, path: Path) -> None:
        from pokemon_price_scheduler.infrastructure.history import history_for_slug
        history = history_for_slug(slug)
        width = 760
        height = 240
        pad = 36
        values = [value for _, own, market in history for value in (own, market) if value is not None]
        if not values:
            path.write_text(self._blank_chart(width, height, "No history yet"), encoding="utf-8")
            return
        low = min(values)
        high = max(values)
        if low == high:
            low = int(low * 0.9)
            high = int(high * 1.1) or 1

        def point(index: int, value: int) -> tuple[float, float]:
            x = pad if len(history) == 1 else pad + (index / (len(history) - 1)) * (width - pad * 2)
            y = height - pad - ((value - low) / (high - low)) * (height - pad * 2)
            return x, y

        own_points = " ".join(f"{x:.1f},{y:.1f}" for i, (_, own, _) in enumerate(history) for x, y in [point(i, own)])
        market_points = " ".join(
            f"{x:.1f},{y:.1f}"
            for i, (_, _, market) in enumerate(history)
            if market is not None
            for x, y in [point(i, market)]
        )
        svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
  <rect width="100%" height="100%" fill="#242428"/>
  <line x1="{pad}" y1="{height-pad}" x2="{width-pad}" y2="{height-pad}" stroke="#3a3a42"/>
  <line x1="{pad}" y1="{pad}" x2="{pad}" y2="{height-pad}" stroke="#3a3a42"/>
  <text x="{pad}" y="22" font-family="monospace" font-size="14" fill="#8b8b96">Price history</text>
  <text x="{width-pad-170}" y="22" font-family="monospace" font-size="12" fill="#4ade80">Market median</text>
  <text x="{width-pad-170}" y="40" font-family="monospace" font-size="12" fill="#818cf8">Your price</text>
  <polyline points="{market_points}" fill="none" stroke="#4ade80" stroke-width="3"/>
  <polyline points="{own_points}" fill="none" stroke="#818cf8" stroke-width="3"/>
</svg>
"""
        path.write_text(svg, encoding="utf-8")

    def _blank_chart(self, width: int, height: int, message: str) -> str:
        return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
  <rect width="100%" height="100%" fill="#0a1628"/>
  <text x="32" y="42" font-family="monospace" font-size="14" fill="#4a7aaa">{message}</text>
</svg>
"""


class CardDetailReport(Report):
    """Writes individual HTML detail pages for each product."""

    def render(self, analyses: list[ProductAnalysis], run_id: int) -> None:
        detail_dir = REPORT_DIR / "cards"
        detail_dir.mkdir(parents=True, exist_ok=True)
        from pokemon_price_scheduler.templates.renderers import render_card_detail
        for analysis in analyses:
            html = render_card_detail(analysis)
            (detail_dir / f"{analysis.product.slug}.html").write_text(html, encoding="utf-8")


class DashboardReport(Report):
    """Writes the main dashboard HTML page."""

    def render(self, analyses: list[ProductAnalysis], run_id: int) -> None:
        from pokemon_price_scheduler.templates.renderers import render_dashboard
        html = render_dashboard(analyses, run_id)
        (REPORT_DIR / "dashboard.html").write_text(html, encoding="utf-8")


class OpportunitiesReport(Report):
    """Writes the buying-opportunities shortlist page."""

    def render(self, analyses: list[ProductAnalysis], run_id: int) -> None:
        from pokemon_price_scheduler.templates.renderers import render_opportunities
        html = render_opportunities(analyses)
        (REPORT_DIR / "opportunities.html").write_text(html, encoding="utf-8")


class ReportEngine:
    """Orchestrates which reports to generate."""

    def __init__(self, reports: list[Report] | None = None):
        self.reports = reports or [
            MarkdownReport(),
            CSVReport(),
            SVGSummaryReport(),
            CardDetailReport(),
            DashboardReport(),
            OpportunitiesReport(),
        ]

    def run(self, analyses: list[ProductAnalysis], run_id: int) -> None:
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        for report in self.reports:
            report.render(analyses, run_id)


def write_reports(analyses: list[ProductAnalysis], run_id: int) -> None:
    """Backward-compatible top-level entry point."""
    ReportEngine().run(analyses, run_id)


def idr(value: int | None) -> str:
    if value is None:
        return "-"
    return f"Rp {value:,.0f}".replace(",", ".")


def pct(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:+.1f}%"