"""Kokoro TTS narrator provider via kokoro-onnx."""

from __future__ import annotations

import logging
import os
import re
import time
from pathlib import Path

import numpy as np

from backend.services.narration.exceptions import NarrationError, NarratorNotFoundError
from backend.services.narration.narrator_provider import NarratorProvider

logger = logging.getLogger(__name__)

DEFAULT_MODEL_PATH = Path("models/kokoro/kokoro-v1.0.onnx")
DEFAULT_VOICES_PATH = Path("models/kokoro/voices-v1.0.bin")
DEFAULT_VOICE = "af_heart"
DEFAULT_SPEED = 1.0
DEFAULT_LANG = "en-us"
# Stay well under Kokoro's 510-phoneme limit (~400 chars is safe).
MAX_CHUNK_CHARS = 400
CHUNK_PAUSE_SECONDS = 0.15


def resolve_kokoro_model_path(path: Path | str | None = None) -> Path:
    if path is not None:
        return Path(path)
    env_path = os.environ.get("KOKORO_MODEL_PATH")
    if env_path:
        return Path(env_path)
    return DEFAULT_MODEL_PATH


def resolve_kokoro_voices_path(path: Path | str | None = None) -> Path:
    if path is not None:
        return Path(path)
    env_path = os.environ.get("KOKORO_VOICES_PATH")
    if env_path:
        return Path(env_path)
    return DEFAULT_VOICES_PATH


def resolve_kokoro_voice(voice: str | None = None) -> str:
    if voice is not None:
        return voice
    return os.environ.get("KOKORO_VOICE", DEFAULT_VOICE)


def split_text_for_kokoro(text: str, max_chars: int = MAX_CHUNK_CHARS) -> list[str]:
    """Split narration into chunks that stay within Kokoro phoneme limits."""
    text = text.strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]

    raw_pieces: list[str] = []
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        sentence = sentence.strip()
        if not sentence:
            continue
        if len(sentence) <= max_chars:
            raw_pieces.append(sentence)
        else:
            raw_pieces.extend(_split_oversized_sentence(sentence, max_chars))

    merged: list[str] = []
    buffer = ""
    for piece in raw_pieces:
        candidate = f"{buffer} {piece}".strip() if buffer else piece
        if len(candidate) <= max_chars:
            buffer = candidate
        else:
            if buffer:
                merged.append(buffer)
            buffer = piece
    if buffer:
        merged.append(buffer)

    return [chunk for chunk in merged if chunk]


def _split_oversized_sentence(segment: str, max_chars: int) -> list[str]:
    """Break an oversized segment by clause marks, then words, then hard cut."""
    for pattern in (r"\s*[,;:]\s*", r"\s+"):
        parts = _split_by_delimiter(segment, pattern, max_chars)
        if len(parts) > 1 or (parts and len(parts[0]) <= max_chars):
            return parts
    return _hard_split(segment, max_chars)


def _split_by_delimiter(text: str, pattern: str, max_chars: int) -> list[str]:
    pieces = [p.strip() for p in re.split(pattern, text) if p.strip()]
    if not pieces:
        return _hard_split(text, max_chars)

    raw: list[str] = []
    for piece in pieces:
        if len(piece) <= max_chars:
            raw.append(piece)
        else:
            raw.extend(_split_by_words(piece, max_chars))

    merged: list[str] = []
    buffer = ""
    for piece in raw:
        candidate = f"{buffer} {piece}".strip() if buffer else piece
        if len(candidate) <= max_chars:
            buffer = candidate
        else:
            if buffer:
                merged.append(buffer)
            buffer = piece
    if buffer:
        merged.append(buffer)
    return merged


def _split_by_words(text: str, max_chars: int) -> list[str]:
    words = text.split()
    chunks: list[str] = []
    buffer: list[str] = []
    length = 0

    for word in words:
        extra = len(word) if not buffer else len(word) + 1
        if length + extra > max_chars and buffer:
            chunks.append(" ".join(buffer))
            buffer = [word]
            length = len(word)
        else:
            buffer.append(word)
            length += extra

    if buffer:
        chunks.append(" ".join(buffer))

    final: list[str] = []
    for chunk in chunks:
        if len(chunk) <= max_chars:
            final.append(chunk)
        else:
            final.extend(_hard_split(chunk, max_chars))
    return final


def _hard_split(text: str, max_chars: int) -> list[str]:
    return [text[i : i + max_chars].strip() for i in range(0, len(text), max_chars) if text[i : i + max_chars].strip()]


class KokoroProvider(NarratorProvider):
    """Generate narration WAV via kokoro-onnx (ONNX Runtime, CPU)."""

    def __init__(
        self,
        model_path: Path | str | None = None,
        voices_path: Path | str | None = None,
        voice: str | None = None,
        speed: float = DEFAULT_SPEED,
        lang: str = DEFAULT_LANG,
    ) -> None:
        self.model_path = resolve_kokoro_model_path(model_path)
        self.voices_path = resolve_kokoro_voices_path(voices_path)
        self.voice = resolve_kokoro_voice(voice)
        self.speed = speed
        self.lang = lang
        self._engine = None

    @property
    def name(self) -> str:
        return "kokoro"

    def verify_installation(self) -> None:
        try:
            import kokoro_onnx  # noqa: F401
            import soundfile  # noqa: F401
        except ImportError as exc:
            raise NarratorNotFoundError(
                "kokoro-onnx is not installed. Run: pip install kokoro-onnx onnxruntime soundfile"
            ) from exc
        logger.debug("kokoro-onnx package available")

    def verify_resources(self) -> None:
        if not self.model_path.is_file():
            raise NarrationError(
                f"Kokoro model not found: {self.model_path}\n"
                "Download kokoro-v1.0.onnx — see docs/kokoro_setup.md"
            )
        if not self.voices_path.is_file():
            raise NarrationError(
                f"Kokoro voices not found: {self.voices_path}\n"
                "Download voices-v1.0.bin — see docs/kokoro_setup.md"
            )
        logger.debug("Kokoro model: %s", self.model_path)
        logger.debug("Kokoro voices: %s", self.voices_path)

    def verify_prerequisites(self) -> None:
        self.verify_installation()
        self.verify_resources()

    def _get_engine(self):
        if self._engine is None:
            from kokoro_onnx import Kokoro

            self._engine = Kokoro(str(self.model_path.resolve()), str(self.voices_path.resolve()))
        return self._engine

    def generate_audio(self, text: str, output_path: str) -> str:
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        resolved_output = output.resolve()

        chunks = split_text_for_kokoro(text)
        if not chunks:
            raise NarrationError("Kokoro received empty narration text")

        engine = self._get_engine()
        logger.info("Kokoro voice: %s", self.voice)
        logger.info("Kokoro model: %s", self.model_path.resolve())
        logger.info("Kokoro output: %s", resolved_output)
        if len(chunks) > 1:
            logger.info("Kokoro chunking: %d segments", len(chunks))
            print(f"  Kokoro: synthesizing {len(chunks)} chunks...", flush=True)

        started_at = time.perf_counter()
        try:
            samples, sample_rate = self._synthesize_chunks(engine, chunks)
        except NarrationError:
            raise
        except Exception as exc:
            raise NarrationError(f"Kokoro synthesis failed: {exc}") from exc

        import soundfile as sf

        sf.write(str(resolved_output), samples, sample_rate)

        elapsed = time.perf_counter() - started_at
        size = resolved_output.stat().st_size
        logger.info("Kokoro execution time: %.1f seconds", elapsed)
        logger.info("Audio generated successfully")
        logger.info("Output audio size: %d bytes", size)
        print(f"  Kokoro finished in {elapsed:.1f} seconds", flush=True)

        if size == 0:
            raise NarrationError(f"Output audio file is empty: {resolved_output}")

        return str(resolved_output)

    def _synthesize_chunks(self, engine, chunks: list[str]) -> tuple[np.ndarray, int]:
        segments: list[np.ndarray] = []
        sample_rate = 24_000

        for index, chunk in enumerate(chunks):
            logger.debug("Kokoro chunk %d/%d (%d chars)", index + 1, len(chunks), len(chunk))
            samples, sample_rate = engine.create(
                chunk,
                voice=self.voice,
                speed=self.speed,
                lang=self.lang,
            )
            segments.append(np.asarray(samples, dtype=np.float32))
            if index < len(chunks) - 1:
                pause = np.zeros(int(sample_rate * CHUNK_PAUSE_SECONDS), dtype=np.float32)
                segments.append(pause)

        if not segments:
            raise NarrationError("Kokoro produced no audio segments")

        return np.concatenate(segments), sample_rate
