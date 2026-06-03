from __future__ import annotations

import csv
from pathlib import Path

from pokemon_price_scheduler.domain.models import ProductAnalysis
from pokemon_price_scheduler.infrastructure.reports import idr, pct


class DebugReportWriter:
    def __init__(self, report_dir: Path = Path("reports")) -> None:
        self.report_dir = report_dir

    def write(self, analyses: list[ProductAnalysis], run_id: int) -> None:
        self.report_dir.mkdir(parents=True, exist_ok=True)
        self._write_markdown(analyses, run_id)
        self._write_csv(analyses)
        if self.report_dir == Path("reports"):
            self._write_legacy_html_outputs(analyses, run_id)

    def _write_legacy_html_outputs(self, analyses: list[ProductAnalysis], run_id: int) -> None:
        from pokemon_price_scheduler.infrastructure.reports import ReportEngine

        ReportEngine().run(analyses, run_id)

    def _write_markdown(self, analyses: list[ProductAnalysis], run_id: int) -> None:
        lines = [f"# Pokemon Price Report - Run {run_id}", ""]
        if analyses:
            lines.extend([f"Generated: {analyses[0].run_at.isoformat()}", ""])
        lines.extend(["## Products", ""])
        for analysis in analyses:
            lines.extend(
                [
                    f"### {analysis.product.title}",
                    f"- Slug: {analysis.product.slug}",
                    f"- Your price: {idr(analysis.product.own_price_idr)}",
                    f"- Market median: {idr(analysis.market_median_idr)}",
                    f"- Global average: {idr(analysis.global_average_idr)}",
                    f"- Delta: {pct(analysis.price_delta_percent)}",
                    f"- Alert: {analysis.alert_level}",
                    f"- Recommendation: {analysis.recommendation}",
                    "",
                ]
            )
        (self.report_dir / "latest.md").write_text("\n".join(lines), encoding="utf-8")

    def _write_csv(self, analyses: list[ProductAnalysis]) -> None:
        fieldnames = [
            "run_at",
            "title",
            "language",
            "own_price_idr",
            "market_min_idr",
            "market_median_idr",
            "global_average_idr",
            "price_delta_percent",
            "alert_level",
            "underpriced_by_idr",
            "underpriced_by_percent",
            "recommendation",
            "ai_summary",
        ]
        with (self.report_dir / "latest.csv").open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for analysis in analyses:
                writer.writerow(analysis.to_row())
