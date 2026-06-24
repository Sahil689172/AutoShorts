"""Standalone Kokoro voice comparison — run before choosing a narrator voice.

Usage (from project root):
    python tools/test_kokoro.py
"""

from __future__ import annotations

import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODEL_PATH = ROOT / "models" / "kokoro" / "kokoro-v1.0.onnx"
VOICES_PATH = ROOT / "models" / "kokoro" / "voices-v1.0.bin"
OUTPUT_DIR = ROOT / "audio" / "voice_tests"
REPORT_PATH = OUTPUT_DIR / "report.txt"

TEST_TEXT = (
    "Have you ever wondered why Lamborghini started as a tractor company? "
    "The answer begins with one frustrated customer."
)

VOICES = (
    "af_heart",
    "af_bella",
    "af_sarah",
    "af_nicole",
    "am_adam",
    "am_michael",
)

LANG = "en-us"


@dataclass
class VoiceResult:
    voice: str
    output_path: Path
    generation_time: float
    output_duration: float


def _probe_duration_ffprobe(wav_path: Path) -> float | None:
    """Return duration in seconds via ffprobe, or None if unavailable."""
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(wav_path),
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    try:
        return float((result.stdout or "").strip())
    except ValueError:
        return None


def _output_duration(samples, sample_rate: int, wav_path: Path) -> float:
    probed = _probe_duration_ffprobe(wav_path)
    if probed is not None:
        return probed
    if sample_rate:
        return len(samples) / sample_rate
    return 0.0


def _write_report(results: list[VoiceResult], sample_rate: int) -> None:
    lines = [
        "Kokoro Voice Comparison Report",
        "=" * 40,
        f"Script: {TEST_TEXT}",
        f"Sample rate: {sample_rate} Hz",
        "",
        f"{'Voice':<12} {'Gen (s)':>8} {'Dur (s)':>8}  File",
        "-" * 40,
    ]
    for row in results:
        lines.append(
            f"{row.voice:<12} {row.generation_time:>8.2f} {row.output_duration:>8.2f}  "
            f"{row.output_path.name}"
        )
    lines.append("")
    lines.append(f"Total voices: {len(results)}")
    lines.append(f"Total generation time: {sum(r.generation_time for r in results):.2f} s")
    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    if not MODEL_PATH.is_file():
        print(f"Error: model not found: {MODEL_PATH}", file=sys.stderr)
        print("Download assets — see docs/kokoro_setup.md", file=sys.stderr)
        return 1
    if not VOICES_PATH.is_file():
        print(f"Error: voices not found: {VOICES_PATH}", file=sys.stderr)
        print("Download assets — see docs/kokoro_setup.md", file=sys.stderr)
        return 1

    try:
        import soundfile as sf
        from kokoro_onnx import Kokoro
    except ImportError as exc:
        print(f"Error: missing dependency: {exc}", file=sys.stderr)
        print("Run: pip install kokoro-onnx onnxruntime soundfile", file=sys.stderr)
        return 1

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Model:  {MODEL_PATH}")
    print(f"Voices: {VOICES_PATH}")
    print(f"Output: {OUTPUT_DIR}")
    print(f"Text:   {TEST_TEXT!r}")
    print()

    kokoro = Kokoro(str(MODEL_PATH), str(VOICES_PATH))
    results: list[VoiceResult] = []
    sample_rate = 24_000

    for voice in VOICES:
        output_path = OUTPUT_DIR / f"voice_{voice}.wav"
        started = time.perf_counter()
        try:
            samples, sample_rate = kokoro.create(
                TEST_TEXT,
                voice=voice,
                speed=1.0,
                lang=LANG,
            )
        except Exception as exc:
            print(f"Error synthesizing {voice}: {exc}", file=sys.stderr)
            return 1

        generation_time = time.perf_counter() - started
        sf.write(str(output_path), samples, sample_rate)
        output_duration = _output_duration(samples, sample_rate, output_path)

        result = VoiceResult(
            voice=voice,
            output_path=output_path,
            generation_time=generation_time,
            output_duration=output_duration,
        )
        results.append(result)

        print(f"Voice:            {voice}")
        print(f"Generation time:  {generation_time:.2f} s")
        print(f"Output duration:  {output_duration:.2f} s")
        print(f"Saved:            {output_path}")
        print()

    _write_report(results, sample_rate)
    print(f"Report: {REPORT_PATH}")
    print("Kokoro voice comparison complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
