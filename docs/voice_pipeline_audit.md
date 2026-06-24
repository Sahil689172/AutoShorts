# Voice Pipeline Audit — Phase 1.1

**Date:** 2026-06-24  
**Scope:** Narration generation from script through final video render  
**Status:** Read-only audit — no code was modified  

---

## Executive Summary

AutoShorts uses **Piper TTS** as its sole narration engine. Piper is invoked as an **external Windows CLI binary** (`piper.exe`) via `subprocess` — there is no Piper Python package in `requirements.txt`. The pipeline contract is a single file: **`audio/output.wav`**. Every downstream phase (captions, scene timing, video mux) reads that path directly.

The voice layer is concentrated in one module (`voice_generator.py`), but Piper-specific assumptions (executable path, ONNX model layout, `--length_scale` CLI flag, Windows DLL handling) are embedded in that module with no abstraction boundary. Replacing Piper requires introducing a **narrator engine interface** while preserving the `audio/output.wav` contract.

---

## Pipeline Flow

```
Topic / Custom Script
        │
        ▼
┌───────────────────────┐
│  ScriptGenerator      │  Phase 1 — Ollama
│  scripts/script.txt   │
└───────────┬───────────┘
            │
            ▼
┌───────────────────────┐
│  VoiceGenerator       │  Phase 2 — Piper TTS
│  audio/output.wav     │  (WAV, engine-native format)
└───────────┬───────────┘
            │
     ┌──────┴──────┬──────────────────┐
     ▼             ▼                  ▼
┌──────────┐ ┌──────────┐    ┌──────────────────┐
│ Caption  │ │ Scene    │    │ VisualTimeline   │
│ Generator│ │ Agent    │    │ Agent            │
│ output   │ │ scenes   │    │ videos/output    │
│ .srt     │ │ .json    │    │ .mp4 (AAC audio) │
└──────────┘ └──────────┘    └──────────────────┘
```

### Step-by-step

| Step | Phase | Module | Input | Output |
|------|-------|--------|-------|--------|
| 1 | Script Generation / Preparation | `script_generator.py` | Topic or pasted script | `scripts/script.txt` |
| 2 | Voice Generation | `voice_generator.py` | `scripts/script.txt` | `audio/output.wav` |
| 3 | Caption Generation | `caption_generator.py` | WAV + script | `captions/output.srt` |
| 4 | Scene Generation | `agents/scene_agent.py` | script + WAV duration | `scenes/scenes.json` |
| 5 | Visual Timeline | `agents/visual_timeline_agent.py` | scenes + WAV + SRT | `videos/output.mp4` |

**Entry points:** `main.py` (CLI) and `backend/pipeline_runner.py` (API) both call `VoiceGenerator().generate()` in Phase 2.

---

## Files Involved

### Core — voice synthesis

| File | Role |
|------|------|
| `voice_generator.py` | **Primary implementation** — Piper subprocess, model paths, WAV output, all voice exceptions |
| `voice.generator.py` | Compatibility re-export shim (dots in filename for legacy imports) |

### Orchestration

| File | Role |
|------|------|
| `main.py` | CLI pipeline — Phase 2 voice generation, catches `PiperNotFoundError` |
| `backend/pipeline_runner.py` | API pipeline — `_phase_voice()` wraps `VoiceGenerator` |
| `pipeline_timing.py` | `PHASE_VOICE = "Voice Generation"` timing label |
| `backend/job_manager.py` | Job phase lists include `"Voice Generation"` |

### Script input (upstream)

| File | Role |
|------|------|
| `script_generator.py` | Writes `scripts/script.txt` via Ollama or `save()` for custom scripts |
| `backend/api.py` | `ScriptGenerateRequest` — custom narration script endpoint |
| `frontend/src/lib/sanitizeScript.js` | Strips narrator labels before submit |
| `frontend/src/utils/sanitizeScript.js` | Duplicate sanitization utility |
| `frontend/src/context/GenerationContext.jsx` | Validates non-empty narration script |
| `frontend/src/pages/HomePage.jsx` | "Paste your narration script here..." UI |

### Audio consumers (downstream)

| File | Role |
|------|------|
| `caption_generator.py` | Probes WAV duration; script-timed SRT (default) or Whisper fallback |
| `agents/subtitle_config.py` | `segment_captions_from_script()` — proportional word timings from narration duration |
| `agents/scene_agent.py` | `probe_audio_duration()` for scene segmentation (~1 visual per 5s) |
| `agents/visual_timeline_agent.py` | **Active video renderer** — FFmpeg mux of WAV into final MP4 |
| `agents/timeline_video_builder.py` | Shared FFmpeg helpers (`probe_duration`, `resolve_ffmpeg_tool`); legacy renderer |
| `video_generator.py` | **Legacy/unused** — background-video renderer; not imported by active pipeline |

### Frontend (progress UX only — no TTS logic)

| File | Role |
|------|------|
| `frontend/src/constants/phases.js` | `"Voice Generation"` phase label |
| `frontend/src/constants/pipeline.js` | Splash log: `"Synthesizing narration audio..."` |
| `frontend/src/pages/LandingPage.jsx` | Marketing copy about voice |

### Documentation & config

| File | Role |
|------|------|
| `Readme.md` | Piper install prerequisite, pipeline diagram |
| `.gitignore` | Ignores `audio/`, `*.wav`, `models/`, `*.onnx` |
| `requirements.txt` | No Piper package; `openai-whisper` consumes WAV for caption fallback |

### External assets (expected on disk, not in repo)

| Path | Role |
|------|------|
| `C:/Tools/piper/piper.exe` | Default Piper binary (Windows) |
| `models/piper/en_US-ryan-high.onnx` | Voice model |
| `models/piper/en_US-ryan-high.onnx.json` | Piper model config |
| `audio/output.wav` | Generated narration (gitignored) |
| `scripts/script.txt` | Narration text input (gitignored) |

---

## Classes

### `voice_generator.py`

| Class | Description |
|-------|-------------|
| `VoiceGenerator` | Main class — reads script, runs Piper, writes WAV |
| `VoiceGeneratorError` | Base exception for voice generation |
| `ScriptNotFoundError` | Script file missing or empty |
| `PiperNotFoundError` | Piper executable missing |
| `VoiceModelNotFoundError` | ONNX model or `.json` config missing |
| `VoiceGenerationError` | Piper subprocess failed or timed out |

### Downstream consumers

| Class | File | Audio relationship |
|-------|------|-------------------|
| `CaptionGenerator` | `caption_generator.py` | Reads `audio/output.wav` for duration; Whisper transcribes same file |
| `SceneAgent` | `agents/scene_agent.py` | Probes WAV duration to size scene list |
| `VisualTimelineAgent` | `agents/visual_timeline_agent.py` | Muxes WAV into `videos/output.mp4`; raises `NarrationNotFoundError` |
| `TimelineVideoBuilder` | `agents/timeline_video_builder.py` | Legacy renderer with same audio mux pattern |
| `VideoGenerator` | `video_generator.py` | Legacy/unused; same `AUDIO_PATH` constant |

---

## Functions

### Voice generation (`voice_generator.py`)

| Function / Method | Description |
|-------------------|-------------|
| `resolve_piper_executable()` | Resolves Piper path: constructor arg → `PIPER_EXECUTABLE` env → `C:/Tools/piper/piper.exe` |
| `calculate_piper_timeout()` | `max(60, word_count × multiplier)` seconds |
| `VoiceGenerator.generate()` | Full 5-step pipeline: verify Piper → verify model → read script → synthesize → verify output |
| `VoiceGenerator._verify_piper_executable()` | File existence check; raises `PiperNotFoundError` |
| `VoiceGenerator._verify_voice_model()` | Checks `.onnx` + `.onnx.json` exist |
| `VoiceGenerator._read_script()` | Reads `scripts/script.txt` |
| `VoiceGenerator._prepare_narration_text()` | Flattens paragraphs/newlines into single-line narration |
| `VoiceGenerator._piper_env()` | Prepends Piper directory to `PATH` (Windows DLL loading) |
| `VoiceGenerator._run_piper()` | Subprocess invocation with `--model`, `--config`, `--length_scale`, `--output_file` |
| `VoiceGenerator._format_piper_failure()` | Error formatting; special hint for Windows DLL exit `0xC0000135` |
| `VoiceGenerator._verify_output()` | Confirms WAV exists and is non-empty |

### Orchestration

| Function | File | Description |
|----------|------|-------------|
| `main()` Phase 2 block | `main.py` | Instantiates `VoiceGenerator`, calls `generate()` |
| `_phase_voice()` | `backend/pipeline_runner.py` | API equivalent; maps exceptions to `PipelineError` |

### Downstream audio functions

| Function | File | Description |
|----------|------|-------------|
| `CaptionGenerator._probe_audio_duration()` | `caption_generator.py` | ffprobe on WAV; word-count estimate fallback |
| `segment_captions_from_script()` | `agents/subtitle_config.py` | Distributes word timings across narration duration |
| `probe_audio_duration()` | `agents/scene_agent.py` | ffprobe narration length for scene planning |
| `estimate_duration_from_script()` | `agents/scene_agent.py` | Fallback when audio probe fails |
| `SceneAgent._analyze_duration()` | `agents/scene_agent.py` | Prefers real audio duration over script estimate |
| `probe_duration()` | `agents/timeline_video_builder.py` | Shared ffprobe helper used by timeline + caption code |
| `VisualTimelineAgent._read_narration_duration()` | `agents/visual_timeline_agent.py` | Reads narration length; raises `NarrationNotFoundError` |
| `VisualTimelineAgent._finalize_with_audio_and_subtitles()` | `agents/visual_timeline_agent.py` | FFmpeg mux: visual MP4 + WAV → `videos/output.mp4` |

---

## Configuration Variables

### Piper-specific (`voice_generator.py`)

| Name | Default | Overridable via | Notes |
|------|---------|-----------------|-------|
| `DEFAULT_PIPER_EXECUTABLE` | `C:/Tools/piper/piper.exe` | — | Hardcoded Windows path |
| `PIPER_EXECUTABLE` | from env or default | `PIPER_EXECUTABLE` env var | **Only Piper env var wired** |
| `VOICE_MODEL` | `models/piper/en_US-ryan-high.onnx` | Constructor arg only | Not env-overridable |
| `VOICE_CONFIG` | `models/piper/en_US-ryan-high.onnx.json` | Constructor arg only | Not env-overridable |
| `SCRIPT_PATH` | `scripts/script.txt` | Constructor arg only | Input |
| `OUTPUT_PATH` | `audio/output.wav` | Constructor arg only | Output |
| `VOICE_SPEED` | `1.25` | Constructor arg only | Passed to Piper as `--length_scale` |
| `PIPER_MIN_TIMEOUT_SECONDS` | `60` | — | Minimum subprocess timeout |
| `PIPER_TIMEOUT_MULTIPLIER` | `1.0` | Constructor arg only | Seconds per word |
| `WINDOWS_DLL_EXIT_CODE` | `3221225781` | — | `0xC0000135` missing-DLL detection |
| `PROGRESS_STEPS` | `5` | — | CLI progress display |

### Related (not Piper, but voice pipeline)

| Name | File | Purpose |
|------|------|---------|
| `CAPTIONS_USE_WHISPER` | `caption_generator.py` | Force Whisper instead of script-timed captions |
| `FFMPEG_EXECUTABLE` | caption/video agents | FFmpeg path |
| `FFPROBE_EXECUTABLE` | scene/caption/timeline agents | Probe `audio/output.wav` duration |
| `SUBTITLE_*` env vars | `agents/subtitle_config.py` | Font, size, margins for burned captions |
| `AUDIO_PATH` | `caption_generator.py`, `scene_agent.py`, `visual_timeline_agent.py`, `timeline_video_builder.py`, `video_generator.py` | Hardcoded `audio/output.wav` in each module |

---

## Output Audio Format

| Stage | Format | Details |
|-------|--------|---------|
| Piper output | **WAV** | `--output_file audio/output.wav`; sample rate/channels determined by Piper model |
| Caption input | WAV | ffprobe duration probe; Whisper transcription reads same file |
| Scene timing input | WAV | ffprobe duration probe |
| Final video audio | **AAC** | `-c:a aac -b:a 192k -ar 48000` in `VisualTimelineAgent._finalize_with_audio_and_subtitles()` |

No MP3 generation anywhere. Piper produces WAV only; FFmpeg transcodes to AAC during final MP4 mux.

---

## Dependencies

### Python packages (`requirements.txt`)

| Package | Voice relevance |
|---------|-----------------|
| *(none for TTS)* | Piper is **not** a pip dependency |
| `openai-whisper>=20231117` | Caption fallback — transcribes the WAV Piper produces |
| `ollama>=0.4.0` | Script generation only (upstream) |
| Other packages | FastAPI, Pillow, requests — unrelated to voice |

### External binaries & assets (manual install)

| Dependency | Purpose |
|------------|---------|
| **Piper TTS** (`piper.exe`) | Narration synthesis |
| **Voice model** (`en_US-ryan-high` ONNX pair) | Piper voice under `models/piper/` |
| **FFmpeg / ffprobe** | Duration probing, audio mux, AAC transcode |
| **Microsoft VC++ Redistributable** | Referenced in Piper DLL error hint (`0xC0000135`) |

---

## Piper-Specific Code Inventory

All Piper references in the repository:

| File | Piper-specific content |
|------|------------------------|
| `voice_generator.py` | **Entire Piper integration** — module docstring, constants (`DEFAULT_PIPER_EXECUTABLE`, `VOICE_MODEL`, `VOICE_CONFIG`, `PIPER_*`, `WINDOWS_DLL_EXIT_CODE`), `resolve_piper_executable()`, `calculate_piper_timeout()`, `PiperNotFoundError`, `VoiceGenerator._run_piper()`, `_piper_env()`, `_format_piper_failure()`, all Piper logging |
| `voice.generator.py` | Re-exports `DEFAULT_PIPER_EXECUTABLE`, `PIPER_EXECUTABLE`, `resolve_piper_executable`, `PiperNotFoundError` |
| `main.py` | Imports and catches `PiperNotFoundError` in Phase 2 |
| `backend/pipeline_runner.py` | `_phase_voice()` imports and catches `PiperNotFoundError` |
| `Readme.md` | Prerequisites and feature table mentioning Piper |

### Piper CLI invocation (core synthesis call)

```python
command = [
    str(self.piper_executable),
    "--model", str(model_path),
    "--config", str(config_path),
    "--length_scale", str(self.voice_speed),
    "--output_file", str(output_path),
]
# Script text fed via subprocess.run(..., input=script_text, text=True)
```

**Piper-specific behaviors embedded in `VoiceGenerator`:**
- Windows-only default executable path (`C:/Tools/piper/piper.exe`)
- ONNX model + JSON config file pair requirement
- `--length_scale` flag for speed control (Piper-specific semantics)
- `cwd` set to Piper directory; `PATH` prepended for DLL resolution
- Windows DLL missing exit code handling (`0xC0000135`)
- Timeout scaled by word count (Piper subprocess can be slow on long scripts)

---

## Current Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Orchestration Layer                   │
│  main.py  │  backend/pipeline_runner._phase_voice()     │
└────────────────────────┬────────────────────────────────┘
                         │ VoiceGenerator().generate()
                         ▼
┌─────────────────────────────────────────────────────────┐
│              voice_generator.py (monolith)               │
│  ┌─────────────┐  ┌──────────────┐  ┌────────────────┐ │
│  │ Script I/O  │→ │ Piper CLI    │→ │ WAV verification│ │
│  │ (read/flat) │  │ subprocess   │  │                │ │
│  └─────────────┘  └──────────────┘  └────────────────┘ │
└────────────────────────┬────────────────────────────────┘
                         │ audio/output.wav (fixed path)
          ┌──────────────┼──────────────┐
          ▼              ▼              ▼
   caption_generator  scene_agent  visual_timeline_agent
   (duration+SRT)     (duration)    (mux→MP4/AAC)
```

**Design characteristics:**
- **Single engine, single file** — all TTS logic lives in `voice_generator.py`
- **File-path contract** — `audio/output.wav` is the integration hub; five modules hardcode this path
- **No interface/protocol** — `VoiceGenerator` is instantiated directly; no factory, registry, or strategy pattern
- **Engine errors leak upstream** — `PiperNotFoundError` is caught explicitly in orchestrators (engine name in exception type)
- **Configuration split** — only `PIPER_EXECUTABLE` is env-configurable; model, speed, and paths are code constants

---

## Weaknesses

| # | Weakness | Impact |
|---|----------|--------|
| 1 | **No abstraction layer** | Replacing Piper requires editing `voice_generator.py` and all `PiperNotFoundError` catch sites |
| 2 | **Engine-specific exception types** | `PiperNotFoundError` propagates to `main.py` and `pipeline_runner.py` |
| 3 | **Hardcoded `audio/output.wav`** | Duplicated as `AUDIO_PATH` in 5 modules; no central path registry |
| 4 | **Windows-centric defaults** | `C:/Tools/piper/piper.exe`, DLL PATH hack, `0xC0000135` handling |
| 5 | **Model locked in code** | `en_US-ryan-high` not configurable via env or API |
| 6 | **Speed control via Piper flag** | `--length_scale` has no portable equivalent across TTS engines |
| 7 | **No audio format negotiation** | Downstream assumes WAV; a new engine might output MP3/OGG/FLAC |
| 8 | **No duration metadata returned** | `generate()` returns only `Path`; consumers re-probe with ffprobe |
| 9 | **Subprocess-only synthesis** | No streaming, chunking, or progress callbacks for long scripts |
| 10 | **Legacy code duplication** | `video_generator.py` and `timeline_video_builder.py` duplicate audio mux logic |
| 11 | **Compatibility shim** | `voice.generator.py` (dots in filename) adds import confusion |
| 12 | **No voice selection in API/frontend** | Users cannot choose voice, speed, or engine from the UI |

---

## Integration Points

These are the boundaries where a new narrator engine must connect:

### 1. Primary synthesis boundary

| Location | Contract |
|----------|----------|
| `VoiceGenerator.generate()` | **Input:** `scripts/script.txt` (UTF-8 text) → **Output:** `audio/output.wav` (non-empty WAV file) |
| Called by | `main.py` (line ~159), `backend/pipeline_runner._phase_voice()` (line ~250) |

### 2. File-path consumers (read `audio/output.wav`)

| Consumer | What it needs from audio |
|----------|--------------------------|
| `CaptionGenerator` | File existence, duration (ffprobe), raw audio (Whisper fallback) |
| `SceneAgent._analyze_duration()` | Duration (ffprobe) or script word-count fallback |
| `VisualTimelineAgent._read_narration_duration()` | Duration (ffprobe); file existence |
| `VisualTimelineAgent._finalize_with_audio_and_subtitles()` | Full audio stream for FFmpeg mux (`-i audio/output.wav`) |

### 3. Exception boundary

| Current | Replacement should use |
|---------|----------------------|
| `PiperNotFoundError` | `NarratorEngineNotFoundError` (engine-agnostic) |
| `VoiceModelNotFoundError` | `NarratorModelNotFoundError` |
| `VoiceGenerationError` | Keep (already generic) |
| `ScriptNotFoundError` | Keep (input validation, not engine-specific) |

### 4. Configuration boundary

| Current | Future |
|---------|--------|
| `PIPER_EXECUTABLE` env var | `NARRATOR_ENGINE` selector + engine-specific config |
| Constructor args on `VoiceGenerator` | `NarratorConfig` dataclass |

### 5. Frontend / API boundary

| Location | Notes |
|----------|-------|
| `backend/job_manager.py` | Phase label `"Voice Generation"` — engine-agnostic, no change needed |
| `frontend/src/constants/phases.js` | Same — display only |
| `backend/api.py` | No voice parameters today; future voice selection would extend job request |

---

## Recommended Abstraction Layer

### Proposed interface

```python
# narrators/base.py (proposed — not yet implemented)

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class NarrationResult:
    """Output of a successful narration synthesis."""
    audio_path: Path
    duration_seconds: float | None = None  # optional; avoids re-probe
    sample_rate: int | None = None
    format: str = "wav"


@dataclass
class NarratorConfig:
    """Engine-agnostic narration settings."""
    script_path: Path = Path("scripts/script.txt")
    output_path: Path = Path("audio/output.wav")
    voice_id: str | None = None       # engine-specific voice identifier
    speed: float = 1.0                # normalized 1.0 = default
    language: str = "en"


class NarratorEngine(ABC):
    """Replaceable narration backend."""

    @abstractmethod
    def synthesize(self, text: str, config: NarratorConfig) -> NarrationResult:
        """Convert text to audio file at config.output_path."""
        ...

    @abstractmethod
    def verify_installation(self) -> None:
        """Raise NarratorEngineNotFoundError if backend is unavailable."""
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """Engine identifier, e.g. 'piper', 'edge-tts', 'coqui'."""
        ...
```

### Proposed structure

```
narrators/
├── __init__.py          # get_narrator(engine_name) factory
├── base.py              # NarratorEngine ABC, NarratorConfig, NarrationResult
├── exceptions.py        # Engine-agnostic exceptions
├── text.py              # _prepare_narration_text() (moved from VoiceGenerator)
├── piper_engine.py      # Current Piper subprocess logic (extracted)
└── (future engines)
```

### Migration plan (high level)

| Phase | Action |
|-------|--------|
| **1. Extract** | Move Piper logic from `VoiceGenerator` into `PiperEngine(NarratorEngine)` |
| **2. Facade** | Keep `VoiceGenerator` as thin facade delegating to `get_narrator()` for backward compatibility |
| **3. Exceptions** | Replace `PiperNotFoundError` with `NarratorEngineNotFoundError`; update `main.py` and `pipeline_runner.py` |
| **4. Centralize paths** | Single `paths.py` or `NarratorConfig` for `AUDIO_PATH` used by all consumers |
| **5. Config** | Add `NARRATOR_ENGINE` env var; optional `NARRATOR_VOICE`, `NARRATOR_SPEED` |
| **6. New engine** | Implement `NarratorEngine` subclass; register in factory |
| **7. Format adapter** | If new engine outputs non-WAV, add optional `normalize_to_wav()` step before writing `audio/output.wav` |

### Factory pattern

```python
# narrators/__init__.py (proposed)

def get_narrator(engine: str | None = None) -> NarratorEngine:
    engine = engine or os.environ.get("NARRATOR_ENGINE", "piper")
    if engine == "piper":
        from narrators.piper_engine import PiperEngine
        return PiperEngine()
    raise NarratorEngineNotFoundError(f"Unknown narrator engine: {engine}")
```

### What should NOT change

- **Output contract:** `audio/output.wav` must remain the hub file until all consumers are updated
- **Phase ordering:** Voice generation stays at Phase 2, before captions and scenes
- **Frontend phase labels:** `"Voice Generation"` is engine-agnostic
- **Downstream ffprobe usage:** Consumers can continue probing duration until `NarrationResult.duration_seconds` is wired through

---

## Appendix: Piper CLI Reference

Current invocation as implemented in `voice_generator.py`:

```
piper.exe
  --model  models/piper/en_US-ryan-high.onnx
  --config models/piper/en_US-ryan-high.onnx.json
  --length_scale 1.25
  --output_file audio/output.wav
  < scripts/script.txt   (stdin)
```

Environment: Piper directory prepended to `PATH`; `cwd` set to Piper directory.

---

*End of Phase 1.1 Voice Pipeline Audit*
