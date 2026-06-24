"""Piper TTS narrator provider."""

from __future__ import annotations

import logging
import os
import subprocess
import time
from pathlib import Path

from backend.services.narration.exceptions import NarrationError, NarratorNotFoundError
from backend.services.narration.narrator_provider import NarratorProvider

logger = logging.getLogger(__name__)

DEFAULT_PIPER_EXECUTABLE = Path("C:/Tools/piper/piper.exe")
DEFAULT_VOICE_MODEL = Path("models/piper/en_US-ryan-high.onnx")
DEFAULT_VOICE_CONFIG = Path("models/piper/en_US-ryan-high.onnx.json")
DEFAULT_VOICE_SPEED = 1.25
PIPER_MIN_TIMEOUT_SECONDS = 60
PIPER_TIMEOUT_MULTIPLIER = 1.0
WINDOWS_DLL_EXIT_CODE = 3221225781


def resolve_piper_executable(path: Path | str | None = None) -> Path:
    """Resolve Piper executable from argument, env var, or default path."""
    if path is not None:
        candidate = Path(path)
        if candidate.is_file():
            return candidate.resolve()

    env_path = os.environ.get("PIPER_EXECUTABLE")
    if env_path:
        candidate = Path(env_path)
        if candidate.is_file():
            return candidate.resolve()

    if DEFAULT_PIPER_EXECUTABLE.is_file():
        return DEFAULT_PIPER_EXECUTABLE.resolve()

    return DEFAULT_PIPER_EXECUTABLE


def calculate_piper_timeout(
    word_count: int,
    multiplier: float = PIPER_TIMEOUT_MULTIPLIER,
    minimum: int = PIPER_MIN_TIMEOUT_SECONDS,
) -> int:
    """Compute subprocess timeout from script length (seconds)."""
    return max(minimum, int(word_count * multiplier))


class PiperProvider(NarratorProvider):
    """Generate narration WAV via the Piper CLI."""

    def __init__(
        self,
        piper_executable: Path | str | None = None,
        voice_model: Path | str = DEFAULT_VOICE_MODEL,
        voice_config: Path | str = DEFAULT_VOICE_CONFIG,
        voice_speed: float = DEFAULT_VOICE_SPEED,
        timeout_multiplier: float = PIPER_TIMEOUT_MULTIPLIER,
    ) -> None:
        self.piper_executable = resolve_piper_executable(piper_executable)
        self.piper_dir = self.piper_executable.parent
        self.voice_model = Path(voice_model)
        self.voice_config = Path(voice_config)
        self.voice_speed = voice_speed
        self.timeout_multiplier = timeout_multiplier

    @property
    def name(self) -> str:
        return "piper"

    def verify_installation(self) -> None:
        if not self.piper_executable.is_file():
            raise NarratorNotFoundError(
                f"Piper executable not found: {self.piper_executable}\n"
                "Install Piper to C:\\Tools\\piper\\piper.exe or set PIPER_EXECUTABLE."
            )
        logger.debug("Piper executable: %s", self.piper_executable)

    def verify_resources(self) -> None:
        if not self.voice_model.is_file():
            raise NarrationError(f"Voice model not found: {self.voice_model}")
        if not self.voice_config.is_file():
            raise NarrationError(f"Voice config not found: {self.voice_config}")
        logger.debug("Voice model: %s", self.voice_model)

    def verify_prerequisites(self) -> None:
        self.verify_installation()
        self.verify_resources()

    def generate_audio(self, text: str, output_path: str) -> str:
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)

        model_path = self.voice_model.resolve()
        config_path = self.voice_config.resolve()
        resolved_output = output.resolve()

        command = [
            str(self.piper_executable),
            "--model",
            str(model_path),
            "--config",
            str(config_path),
            "--length_scale",
            str(self.voice_speed),
            "--output_file",
            str(resolved_output),
        ]

        logger.info("Piper executable: %s", self.piper_executable)
        logger.info("Voice model: %s", model_path)
        logger.info("Voice config: %s", config_path)
        logger.info("Voice speed (length_scale): %s", self.voice_speed)
        logger.info("Output WAV: %s", resolved_output)
        logger.info("Piper command: %s", " ".join(command))

        word_count = len(text.split())
        timeout = calculate_piper_timeout(word_count, self.timeout_multiplier)
        logger.info("Estimated timeout: %d seconds", timeout)
        print(f"  Estimated timeout: {timeout} seconds", flush=True)

        started_at = time.perf_counter()
        try:
            result = subprocess.run(
                command,
                input=text,
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                timeout=timeout,
                cwd=str(self.piper_dir),
                env=self._piper_env(),
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            elapsed = time.perf_counter() - started_at
            logger.error(
                "Piper timed out after %.1f seconds (limit: %d seconds)",
                elapsed,
                timeout,
            )
            raise NarrationError(f"Piper timed out after {timeout} seconds") from exc
        except OSError as exc:
            raise NarrationError(f"Failed to run Piper: {exc}") from exc

        elapsed = time.perf_counter() - started_at
        logger.info("Piper execution time: %.1f seconds", elapsed)
        print(f"  Piper finished in {elapsed:.1f} seconds", flush=True)

        stdout = result.stdout or ""
        stderr = result.stderr or ""
        logger.info("Piper return code: %s", result.returncode)
        logger.info("Piper stdout: %s", stdout.strip())
        logger.info("Piper stderr: %s", stderr.strip())

        if result.returncode != 0:
            raise NarrationError(
                self._format_piper_failure(result.returncode, stdout, stderr)
            )

        if not resolved_output.is_file():
            raise NarrationError(f"Piper did not create output file: {resolved_output}")
        size = resolved_output.stat().st_size
        if size == 0:
            raise NarrationError(f"Output audio file is empty: {resolved_output}")
        logger.info("Output audio size: %d bytes", size)

        return str(resolved_output)

    def _piper_env(self) -> dict[str, str]:
        """Ensure Piper's directory is on PATH so bundled DLLs load on Windows."""
        env = os.environ.copy()
        piper_dir = str(self.piper_dir)
        env["PATH"] = piper_dir + os.pathsep + env.get("PATH", "")
        return env

    @staticmethod
    def _format_piper_failure(returncode: int, stdout: str, stderr: str) -> str:
        message = (
            f"Piper synthesis failed.\n"
            f"  return code: {returncode}\n"
            f"  stderr: {stderr.strip() or '(empty)'}\n"
            f"  stdout: {stdout.strip() or '(empty)'}"
        )
        if returncode == WINDOWS_DLL_EXIT_CODE:
            message += (
                "\n\nHint: Windows error 0xC0000135 — missing DLL. Ensure all Piper "
                f"files are in {DEFAULT_PIPER_EXECUTABLE.parent} and install the "
                "Microsoft Visual C++ 2015-2022 Redistributable (x64)."
            )
        return message
