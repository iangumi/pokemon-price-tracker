"""Backward-compatibility shim — re-exports from infrastructure layer."""

from .infrastructure.history import (
    connect,
    init_db,
    save_run,
    get_observations_for_slug,
    history_for_slug,
    get_all_products_with_trend,
)

__all__ = [
    "connect",
    "init_db",
    "save_run",
    "get_observations_for_slug",
    "history_for_slug",
    "get_all_products_with_trend",
]