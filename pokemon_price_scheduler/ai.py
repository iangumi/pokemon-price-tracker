"""Backward-compatibility shim — re-exports from infrastructure layer."""

from .infrastructure.ai import (
    MiniMaxClient,
    attach_ai_summaries,
    build_repricing_advice_payload,
    build_repricing_advice_prompt,
    build_summary_prompt,
    generate_repricing_advice,
    load_project_env,
    parse_env_line,
    parse_repricing_advice_response,
    repricing_advice_input_hash,
    strip_thinking,
)

__all__ = [
    "MiniMaxClient",
    "attach_ai_summaries",
    "build_repricing_advice_payload",
    "build_repricing_advice_prompt",
    "build_summary_prompt",
    "generate_repricing_advice",
    "load_project_env",
    "parse_env_line",
    "parse_repricing_advice_response",
    "repricing_advice_input_hash",
    "strip_thinking",
]
