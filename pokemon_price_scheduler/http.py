"""Backward-compatibility shim — re-exports from infrastructure layer."""

from .infrastructure.http import fetch_text

__all__ = ["fetch_text"]