"""Backward-compatibility shim — re-exports from infrastructure layer."""

from .infrastructure.http import (
    classify_fetch_error,
    fetch_text,
    is_scrapling_available,
    resolve_fetch_backend,
    select_fetch_backend,
)

__all__ = [
    "fetch_text",
    "select_fetch_backend",
    "resolve_fetch_backend",
    "is_scrapling_available",
    "classify_fetch_error",
]
