"""Abstract base class for narrator providers."""

from __future__ import annotations

from abc import ABC, abstractmethod


class NarratorProvider(ABC):
    """Replaceable text-to-speech backend."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider identifier (e.g. ``piper``)."""

    def verify_installation(self) -> None:
        """Step 1: confirm the provider runtime is available."""
        self.verify_prerequisites()

    def verify_resources(self) -> None:
        """Step 2: confirm voices/models/assets (optional; default no-op)."""

    @abstractmethod
    def verify_prerequisites(self) -> None:
        """Raise ``NarratorNotFoundError`` or ``NarrationError`` if unavailable."""

    @abstractmethod
    def generate_audio(self, text: str, output_path: str) -> str:
        """Synthesize narration and write to ``output_path``. Returns the path."""
