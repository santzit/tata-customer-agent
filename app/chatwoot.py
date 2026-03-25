"""Backward-compatible re-export shim.

The canonical implementation lives in :mod:`app.services.chatwoot_client`.
This module re-exports ``ChatwootClient`` so that existing imports remain
valid without modification.
"""

from app.services.chatwoot_client import ChatwootClient  # noqa: F401

__all__ = ["ChatwootClient"]
