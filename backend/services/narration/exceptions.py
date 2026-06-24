"""Engine-agnostic narration exceptions."""


class NarrationError(Exception):
    """Base error for narration generation."""


class NarratorNotFoundError(NarrationError):
    """Configured narrator provider is missing or unavailable."""


class ScriptNotFoundError(NarrationError):
    """Script file is missing or empty."""
