"""Backward-compatibility shim — re-exports from infrastructure layer."""

from .infrastructure.history import (
    connect,
    close_connection,
    init_db,
    save_run,
    get_observations_for_slug,
    history_for_slug,
    get_all_products_with_trend,
    price_history_for_slug,
    price_trend_for_slug,
    record_price_snapshot,
    repricing_queue,
    suggested_prices,
    recommended_action,
)

__all__ = [
    "connect",
    "close_connection",
    "init_db",
    "save_run",
    "get_observations_for_slug",
    "history_for_slug",
    "get_all_products_with_trend",
    "price_history_for_slug",
    "price_trend_for_slug",
    "record_price_snapshot",
    "repricing_queue",
    "suggested_prices",
    "recommended_action",
]
