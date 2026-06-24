"""Load narrator providers and orchestrate narration generation."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from backend.services.narration.exceptions import NarrationError, NarratorNotFoundError, ScriptNotFoundError
from backend.services.narration.narrator_provider import NarratorProvider
from backend.services.narration.text_utils import prepare_narration_text

logger = logging.getLogger(__name__)

DEFAULT_PROVIDER = "piper"
DEFAULT_SCRIPT_PATH = Path("scripts/script.txt")
DEFAULT_OUTPUT_PATH = Path("audio/output.wav")
PROGRESS_STEPS = 5


def load_provider(
    name: str | None = None,
    *,
    piper_executable: Path | str | None = None,
    voice_model: Path | str | None = None,
    voice_config: Path | str | None = None,
    voice_speed: float | None = None,
    timeout_multiplier: float | None = None,
) -> NarratorProvider:
    """Instantiate the configured narrator provider."""
    provider_name = (name or os.environ.get("NARRATOR_PROVIDER", DEFAULT_PROVIDER)).lower()

    if provider_name == "piper":
        from backend.services.narration.providers.piper_provider import PiperProvider

        kwargs: dict = {}
        if piper_executable is not None:
            kwargs["piper_executable"] = piper_executable
        if voice_model is not None:
            kwargs["voice_model"] = voice_model
        if voice_config is not None:
            kwargs["voice_config"] = voice_config
        if voice_speed is not None:
            kwargs["voice_speed"] = voice_speed
        if timeout_multiplier is not None:
            kwargs["timeout_multiplier"] = timeout_multiplier
        return PiperProvider(**kwargs)

    raise NarratorNotFoundError(
        f"Unknown narrator provider: {provider_name!r}. "
        f"Set NARRATOR_PROVIDER to a supported value (default: {DEFAULT_PROVIDER!r})."
    )


class NarrationManager:
    """Read script, delegate synthesis to a provider, return audio path."""

    def __init__(
        self,
        provider: NarratorProvider | None = None,
        provider_name: str | None = None,
        script_path: Path | str = DEFAULT_SCRIPT_PATH,
        output_path: Path | str = DEFAULT_OUTPUT_PATH,
        *,
        piper_executable: Path | str | None = None,
        voice_model: Path | str | None = None,
        voice_config: Path | str | None = None,
        voice_speed: float | None = None,
        timeout_multiplier: float | None = None,
    ) -> None:
        self.script_path = Path(script_path)
        self.output_path = Path(output_path)
        self.provider = provider or load_provider(
            provider_name,
            piper_executable=piper_executable,
            voice_model=voice_model,
            voice_config=voice_config,
            voice_speed=voice_speed,
            timeout_multiplier=timeout_multiplier,
        )

    def generate(self) -> Path:
        """Read script, synthesize narration, and save audio/output.wav."""
        self._print_progress(1, f"Verifying narrator ({self.provider.name})...")
        self.provider.verify_installation()

        self._print_progress(2, "Verifying voice model...")
        self.provider.verify_resources()

        self._print_progress(3, "Reading script...")
        script_text = self._read_script()

        self._print_progress(4, f"Generating narration ({self.provider.name})...")
        narration = prepare_narration_text(script_text)
        audio_path = self.provider.generate_audio(narration, str(self.output_path))

        self._print_progress(5, "Verifying output audio...")
        self._verify_output(Path(audio_path))
        logger.info("Voice narration saved to %s", self.output_path.resolve())
        return self.output_path.resolve()

    def _print_progress(self, step: int, message: str) -> None:
        print(f"[{step}/{PROGRESS_STEPS}] {message}", flush=True)
        logger.info("%s", message)

    def _read_script(self) -> str:
        if not self.script_path.is_file():
            raise ScriptNotFoundError(
                f"Script not found: {self.script_path}. Run Phase 1 first."
            )
        try:
            text = self.script_path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise ScriptNotFoundError(f"Cannot read script: {exc}") from exc
        if not text:
            raise ScriptNotFoundError(f"Script is empty: {self.script_path}")
        word_count = len(text.split())
        logger.info("Loaded script (%d words) from %s", word_count, self.script_path)
        return text

    def _verify_output(self, path: Path) -> None:
        if not path.is_file():
            raise NarrationError(f"Narration output file was not created: {path}")
        size = path.stat().st_size
        if size == 0:
            raise NarrationError(f"Narration output file is empty: {path}")
