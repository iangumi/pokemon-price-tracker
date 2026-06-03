"""Backward-compatibility shim — re-exports from infrastructure layer."""

from .infrastructure.ai import (
    MiniMaxClient,
    attach_ai_summaries,
    build_summary_prompt,
    strip_thinking,
)

__all__ = ["MiniMaxClient", "attach_ai_summaries", "build_summary_prompt", "strip_thinking"]
