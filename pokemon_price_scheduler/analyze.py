"""Backward-compatibility shim — re-exports from domain layer."""

from .domain.analysis import analyze_product, score_observations, relevance_score

__all__ = ["analyze_product", "score_observations", "relevance_score"]