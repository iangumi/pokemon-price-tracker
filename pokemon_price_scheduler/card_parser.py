"""Backward-compatibility shim — re-exports from domain layer."""

from .domain.card_parser import CardIdentity, parse_card_identity

__all__ = ["CardIdentity", "parse_card_identity"]