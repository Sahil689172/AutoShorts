"""Phase 2: Convert script text to narration audio (backward-compatible facade)."""

from __future__ import annotations

from pathlib import Path

from backend.services.narration.exceptions import NarrationError, NarratorNotFoundError, ScriptNotFoundError
from backend.services.narration.narration_manager import NarrationManager
from backend.services.narration.providers.piper_provider import (
    DEFAULT_PIPER_EXECUTABLE,
    DEFAULT_VOICE_CONFIG,
    DEFAULT_VOICE_MODEL,
    DEFAULT_VOICE_SPEED,
    PIPER_TIMEOUT_MULTIPLIER,
    calculate_piper_timeout,
    resolve_piper_executable,
)

# Re-export Piper constants for backward compatibility.
PIPER_EXECUTABLE = DEFAULT_PIPER_EXECUTABLE
VOICE_MODEL = DEFAULT_VOICE_MODEL
VOICE_CONFIG = DEFAULT_VOICE_CONFIG
VOICE_SPEED = DEFAULT_VOICE_SPEED
SCRIPT_PATH = Path("scripts/script.txt")
OUTPUT_PATH = Path("audio/output.wav")

# Legacy exception aliases (engine-agnostic types preferred in new code).
VoiceGeneratorError = NarrationError
PiperNotFoundError = NarratorNotFoundError
VoiceModelNotFoundError = NarrationError
VoiceGenerationError = NarrationError


class VoiceGenerator:
    """Generate narration WAV from scripts/script.txt via the configured provider."""

    def __init__(
        self,
        piper_executable: Path | str | None = None,
        voice_model: Path | str = VOICE_MODEL,
        voice_config: Path | str = VOICE_CONFIG,
        script_path: Path | str = SCRIPT_PATH,
        output_path: Path | str = OUTPUT_PATH,
        voice_speed: float = VOICE_SPEED,
        timeout_multiplier: float = PIPER_TIMEOUT_MULTIPLIER,
    ) -> None:
        self._manager = NarrationManager(
            script_path=script_path,
            output_path=output_path,
            piper_executable=piper_executable,
            voice_model=voice_model,
            voice_config=voice_config,
            voice_speed=voice_speed,
            timeout_multiplier=timeout_multiplier,
        )

    def generate(self) -> Path:
        """Read script, synthesize narration, and save audio/output.wav."""
        return self._manager.generate()


__all__ = [
    "DEFAULT_PIPER_EXECUTABLE",
    "OUTPUT_PATH",
    "PIPER_EXECUTABLE",
    "PiperNotFoundError",
    "SCRIPT_PATH",
    "ScriptNotFoundError",
    "VOICE_CONFIG",
    "VOICE_MODEL",
    "VOICE_SPEED",
    "VoiceGenerationError",
    "VoiceGenerator",
    "VoiceGeneratorError",
    "VoiceModelNotFoundError",
    "calculate_piper_timeout",
    "resolve_piper_executable",
]
