# Narration Architecture — Phase 1.2

**Date:** 2026-06-24  
**Status:** Provider-based abstraction layer implemented  

---

## Overview

AutoShorts narration is now routed through a **provider-based architecture** under `backend/services/narration/`. The pipeline contract is unchanged: all engines must write **`audio/output.wav`**, and every downstream consumer (captions, scenes, video renderer) continues to work without modification.

The default provider is **Piper** (`NARRATOR_PROVIDER=piper`). Existing CLI commands, API jobs, and UI progress labels are unchanged.

---

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                     Entry Points (unchanged)                         │
│   main.py                    backend/pipeline_runner._phase_voice()  │
│        │                              │                              │
│        └──────────────┬───────────────┘                              │
│                       ▼                                              │
│              voice_generator.VoiceGenerator  (facade)                │
└───────────────────────────────┬─────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    backend/services/narration/                       │
│                                                                      │
│   ┌──────────────────┐      NARRATOR_PROVIDER env var                │
│   │ NarrationManager │◄──── (default: piper)                         │
│   └────────┬─────────┘                                               │
│            │ load_provider()                                         │
│            ▼                                                         │
│   ┌──────────────────┐                                               │
│   │ NarratorProvider │  ABC                                           │
│   │  generate_audio()│                                               │
│   └────────┬─────────┘                                               │
│            │                                                         │
│            ▼                                                         │
│   ┌──────────────────┐                                               │
│   │  PiperProvider   │  providers/piper_provider.py                  │
│   │  (Piper CLI)     │                                               │
│   └────────┬─────────┘                                               │
└────────────┼────────────────────────────────────────────────────────┘
             │
             ▼
      audio/output.wav  ◄─── FIXED CONTRACT (unchanged)
             │
    ┌────────┼────────┬─────────────────┐
    ▼        ▼        ▼                 ▼
 Caption   Scene   VisualTimeline   (unchanged)
 Generator  Agent      Agent
```

---

## Package Structure

```
backend/services/narration/
├── __init__.py                 # Public exports
├── exceptions.py               # NarrationError, NarratorNotFoundError, ScriptNotFoundError
├── narrator_provider.py        # NarratorProvider ABC
├── narration_manager.py        # Orchestration + load_provider()
├── text_utils.py               # prepare_narration_text()
└── providers/
    ├── __init__.py
    └── piper_provider.py       # PiperProvider (all Piper-specific logic)
```

### Root-level facade

`voice_generator.py` remains the backward-compatible entry point used by `main.py` and `pipeline_runner.py`. It delegates to `NarrationManager` and re-exports legacy constants and exception aliases.

---

## Provider System

### Abstract interface

```python
class NarratorProvider(ABC):
    @property
    def name(self) -> str: ...

    def verify_installation(self) -> None: ...
    def verify_resources(self) -> None: ...      # optional; default no-op
    def verify_prerequisites(self) -> None: ...

    def generate_audio(self, text: str, output_path: str) -> str: ...
```

| Method | Purpose |
|--------|---------|
| `verify_installation()` | Step 1 — runtime/binary available |
| `verify_resources()` | Step 2 — models, voices, credentials |
| `generate_audio()` | Synthesize text → WAV at `output_path` |
| `name` | Provider identifier for logging |

### NarrationManager flow

1. Load provider via `NARRATOR_PROVIDER` (default `piper`)
2. Verify installation (step 1)
3. Verify resources (step 2)
4. Read `scripts/script.txt`
5. Flatten text via `prepare_narration_text()`
6. Call `provider.generate_audio(text, "audio/output.wav")`
7. Verify output file exists and is non-empty
8. Return resolved `Path` to `audio/output.wav`

### Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `NARRATOR_PROVIDER` | `piper` | Active narrator provider |
| `PIPER_EXECUTABLE` | `C:/Tools/piper/piper.exe` | Piper binary path (Piper only) |

Voice model, speed, and paths remain configurable via `VoiceGenerator` constructor arguments (passed through to `PiperProvider`).

---

## Exceptions

Engine-agnostic exceptions live in `backend/services/narration/exceptions.py`:

| Exception | When raised |
|-----------|-------------|
| `NarrationError` | Base class; synthesis failures, empty output, model missing |
| `NarratorNotFoundError` | Provider unknown or runtime unavailable |
| `ScriptNotFoundError` | `scripts/script.txt` missing or empty |

`main.py` and `pipeline_runner.py` now catch `NarratorNotFoundError`, `ScriptNotFoundError`, and `NarrationError` — no Piper-specific exceptions leak upstream.

Legacy aliases in `voice_generator.py` (`PiperNotFoundError`, `VoiceGeneratorError`, etc.) remain for backward compatibility with older imports.

---

## Piper Provider

All Piper-specific logic was moved to `providers/piper_provider.py`:

- Executable resolution (`PIPER_EXECUTABLE`, `C:/Tools/piper/piper.exe`)
- ONNX model + config validation
- Subprocess invocation (`--model`, `--config`, `--length_scale`, `--output_file`)
- Windows DLL `PATH` handling and `0xC0000135` error hints
- Timeout calculation from word count

No Piper references remain in orchestration code (`main.py`, `pipeline_runner.py`).

---

## Adding a Future Provider

### Step 1 — Implement the provider

Create `backend/services/narration/providers/<name>_provider.py`:

```python
from backend.services.narration.narrator_provider import NarratorProvider
from backend.services.narration.exceptions import NarrationError, NarratorNotFoundError


class EdgeTtsProvider(NarratorProvider):
    @property
    def name(self) -> str:
        return "edge-tts"

    def verify_prerequisites(self) -> None:
        # Check dependencies
        ...

    def generate_audio(self, text: str, output_path: str) -> str:
        # MUST write WAV to output_path (or convert before returning)
        ...
        return output_path
```

### Step 2 — Register in `load_provider()`

In `narration_manager.py`:

```python
if provider_name == "edge-tts":
    from backend.services.narration.providers.edge_tts_provider import EdgeTtsProvider
    return EdgeTtsProvider()
```

### Step 3 — Configure

```bash
NARRATOR_PROVIDER=edge-tts
```

### Requirements for any new provider

1. **Write to `audio/output.wav`** (or the path passed to `generate_audio`)
2. **Output must be a valid WAV** readable by ffprobe, Whisper, and FFmpeg
3. **Raise `NarratorNotFoundError`** when the engine/runtime is missing
4. **Raise `NarrationError`** for synthesis failures
5. **Do not modify downstream modules** — captions, scenes, and video renderer read the same file

If a provider natively outputs MP3/OGG, add a normalization step inside the provider to produce WAV before returning.

---

## Migration Notes

### What changed (Phase 1.2)

| Before | After |
|--------|-------|
| Piper logic in `voice_generator.py` | Piper logic in `providers/piper_provider.py` |
| `PiperNotFoundError` in orchestrators | `NarratorNotFoundError` |
| Monolithic `VoiceGenerator` | `VoiceGenerator` → `NarrationManager` → `PiperProvider` |
| No provider selection | `NARRATOR_PROVIDER` env var |

### What did NOT change

| Item | Status |
|------|--------|
| Output path `audio/output.wav` | Unchanged |
| `VoiceGenerator().generate()` API | Unchanged |
| Pipeline phase order | Unchanged |
| CLI (`main.py`) behavior | Unchanged |
| API (`pipeline_runner.py`) behavior | Unchanged |
| Frontend phase labels | Unchanged |
| Caption / scene / video modules | Unchanged |
| `PIPER_EXECUTABLE` env var | Unchanged (Piper provider only) |

### Import guidance

| Use case | Import from |
|----------|-------------|
| New code | `backend.services.narration` |
| Engine-agnostic exceptions | `backend.services.narration.exceptions` |
| Legacy / external scripts | `voice_generator` (facade) |

### Backward-compatible exception mapping

| Legacy (`voice_generator`) | Engine-agnostic |
|----------------------------|-----------------|
| `VoiceGeneratorError` | `NarrationError` |
| `PiperNotFoundError` | `NarratorNotFoundError` |
| `VoiceModelNotFoundError` | `NarrationError` |
| `VoiceGenerationError` | `NarrationError` |
| `ScriptNotFoundError` | `ScriptNotFoundError` (unchanged) |

---

## Downstream Contract

These modules continue to read `audio/output.wav` directly — **no changes required**:

| Module | Usage |
|--------|-------|
| `caption_generator.py` | Duration probe + Whisper fallback |
| `agents/scene_agent.py` | `probe_audio_duration()` for scene count |
| `agents/visual_timeline_agent.py` | FFmpeg mux into `videos/output.mp4` |
| `agents/timeline_video_builder.py` | Shared `probe_duration()` helper |

The abstraction layer ends at `audio/output.wav`. Everything after that is format-agnostic as long as the file is a valid WAV.

---

*End of Phase 1.2 Narration Architecture documentation*
