"""Backward-compatibility shim — re-exports from infrastructure layer."""

from .infrastructure.reports import (
    write_reports,
    ReportEngine,
    MarkdownReport,
    CSVReport,
    SVGSummaryReport,
    CardDetailReport,
    DashboardReport,
    OpportunitiesReport,
)
from .infrastructure.reports import idr, pct

__all__ = [
    "write_reports",
    "ReportEngine",
    "MarkdownReport",
    "CSVReport",
    "SVGSummaryReport",
    "CardDetailReport",
    "DashboardReport",
    "OpportunitiesReport",
    "idr",
    "pct",
]