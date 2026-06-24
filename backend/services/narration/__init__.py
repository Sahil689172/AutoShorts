"""Narration service — provider-based text-to-speech."""

from backend.services.narration.exceptions import NarrationError, NarratorNotFoundError
from backend.services.narration.narration_manager import NarrationManager

__all__ = [
    "NarrationError",
    "NarrationManager",
    "NarratorNotFoundError",
]
