# Phase 1.2 Verification Audit

**Date:** 2026-06-24  
**Scope:** Narrator abstraction layer (`backend/services/narration/`)  
**Method:** Read-only codebase search and pipeline trace — no code modified  

---

## Executive Summary

Phase 1.2 successfully introduced a provider-based narration architecture. Piper synthesis logic is isolated in `PiperProvider`, orchestration code (`main.py`, `backend/pipeline_runner.py`) uses engine-agnostic exceptions, and the `audio/output.wav` contract is preserved with zero downstream changes.

Residual coupling exists in the **compatibility facade** (`voice_generator.py`), **provider factory** (`narration_manager.load_provider()`), and **documentation** (`Readme.md` still references Piper only). These do not block Kokoro integration but should be addressed during Phase 1.3.

---

## 1. Provider Isolation

### 1.1 Search: `piper.exe`

| File | Line | Content |
|------|------|---------|
| `backend/services/narration/providers/piper_provider.py` | 16 | `DEFAULT_PIPER_EXECUTABLE = Path("C:/Tools/piper/piper.exe")` |
| `backend/services/narration/providers/piper_provider.py` | 79 | Error message: `Install Piper to C:\Tools\piper\piper.exe or set PIPER_EXECUTABLE.` |
| `docs/voice_pipeline_audit.md` | 11, 118, 157, 197, 249, 282, 330, 490 | Historical audit references |
| `docs/narration_architecture.md` | 119, 145 | Architecture documentation |

**Application code:** `piper.exe` appears only in `piper_provider.py` (lines 16, 79).

**Verdict:** **PASS** — executable path is confined to the Piper provider implementation.

---

### 1.2 Search: `Piper` (application `.py` files)

| File | Line(s) | Category | Notes |
|------|---------|----------|-------|
| `backend/services/narration/providers/piper_provider.py` | 1, 26, 44, 53–54, 58, 64–65, 73, 76–81, 103, 114, 119, 122, 136–137, 143, 147, 149, 152–153, 157–159, 163, 167, 175–176, 183, 185, 192 | **Provider** | Expected — all Piper runtime logic |
| `backend/services/narration/narration_manager.py` | 15, 24, 33–34, 37–38, 47, 65, 75 | **Factory** | Provider registry + `piper_executable` kwargs |
| `backend/services/narration/narrator_provider.py` | 14 | **ABC** | Docstring example only (`e.g. piper`) |
| `voice_generator.py` | 9–16, 19, 29, 39, 50, 66, 76–77 | **Facade** | Imports/re-exports Piper constants; passes `piper_executable` |
| `voice.generator.py` | 10, 16, 23, 27 | **Compat shim** | Re-exports Piper symbols |

**Not found in (confirmed clean):**

| Area | Files checked | Result |
|------|---------------|--------|
| API | `backend/api.py` | No Piper references |
| UI | `frontend/**` | No Piper references |
| Video renderer | `agents/visual_timeline_agent.py`, `agents/timeline_video_builder.py`, `video_generator.py` | No Piper references |
| Pipeline runner | `backend/pipeline_runner.py` | No Piper references |
| CLI orchestration | `main.py` | No Piper references |
| Caption / scene agents | `caption_generator.py`, `agents/scene_agent.py` | No Piper references |

**Documentation (non-runtime):**

| File | Line(s) |
|------|---------|
| `Readme.md` | 93, 100, 186 |
| `docs/narration_architecture.md` | Multiple |
| `docs/voice_pipeline_audit.md` | Multiple (pre-1.2 audit; partially stale) |

**Verdict:** **PASS with notes** — Piper runtime logic is isolated to `piper_provider.py`. Acceptable residual references exist in the factory (`load_provider`), backward-compat facade, and docs. No Piper logic in API, UI, renderer, or orchestration.

---

### 1.3 Search: `PiperNotFoundError`

| File | Line | Usage |
|------|------|-------|
| `voice_generator.py` | 29 | `PiperNotFoundError = NarratorNotFoundError` (legacy alias) |
| `voice_generator.py` | 66 | `__all__` export |
| `voice.generator.py` | 10, 27 | Re-export for legacy imports |
| `docs/narration_architecture.md` | 137, 216, 246 | Documentation |
| `docs/voice_pipeline_audit.md` | 71, 135, 160, 262–265, 318, 327–328, 366, 457 | Stale pre-1.2 references |

**Not found in:**

- `main.py` — uses `NarratorNotFoundError` (line 154)
- `backend/pipeline_runner.py` — uses `NarratorNotFoundError` (line 249)
- `backend/api.py`
- `frontend/**`
- `piper_provider.py` — raises `NarratorNotFoundError` (line 77)

**Verdict:** **PASS** — `PiperNotFoundError` is not used in orchestration, API, UI, or renderer. It survives only as a backward-compatible alias in `voice_generator.py` / `voice.generator.py`.

---

## 2. Provider Architecture

### 2.1 Verified Components

| Component | File | Class / Symbol | Status |
|-----------|------|----------------|--------|
| Abstract interface | `backend/services/narration/narrator_provider.py` | `NarratorProvider` | **Exists** |
| Piper implementation | `backend/services/narration/providers/piper_provider.py` | `PiperProvider` | **Exists** |
| Orchestrator | `backend/services/narration/narration_manager.py` | `NarrationManager`, `load_provider()` | **Exists** |
| Exceptions | `backend/services/narration/exceptions.py` | `NarrationError`, `NarratorNotFoundError`, `ScriptNotFoundError` | **Exists** |
| Text prep | `backend/services/narration/text_utils.py` | `prepare_narration_text()` | **Exists** |
| Package exports | `backend/services/narration/__init__.py` | `NarrationManager`, `NarrationError`, `NarratorNotFoundError` | **Exists** |
| Backward-compat facade | `voice_generator.py` | `VoiceGenerator` | **Exists** — delegates to `NarrationManager` |

### 2.2 Class Relationships

```
NarratorProvider (ABC)
    │
    ├── verify_installation()     [default → verify_prerequisites()]
    ├── verify_resources()        [default no-op; Piper overrides]
    ├── verify_prerequisites()    [abstract]
    ├── generate_audio(text, output_path) → str  [abstract]
    └── name → str                [abstract property]
         │
         ▼
PiperProvider(NarratorProvider)
    └── Piper CLI subprocess synthesis

NarrationManager
    ├── provider: NarratorProvider  (from load_provider() or injected)
    ├── script_path → scripts/script.txt
    ├── output_path → audio/output.wav
    └── generate() → Path

VoiceGenerator (facade)
    └── _manager: NarrationManager
        └── generate() → Path
```

### 2.3 `NarratorProvider` Interface

```python
class NarratorProvider(ABC):
    @property
    def name(self) -> str: ...

    def verify_installation(self) -> None: ...
    def verify_resources(self) -> None: ...
    def verify_prerequisites(self) -> None: ...

    def generate_audio(self, text: str, output_path: str) -> str: ...
```

**Verdict:** **PASS** — all required architectural components exist and are wired correctly.

---

## 3. Environment Configuration

### 3.1 `NARRATOR_PROVIDER`

| Aspect | Location | Detail |
|--------|----------|--------|
| **Defined (default)** | `backend/services/narration/narration_manager.py:15` | `DEFAULT_PROVIDER = "piper"` |
| **Consumed** | `backend/services/narration/narration_manager.py:31` | `os.environ.get("NARRATOR_PROVIDER", DEFAULT_PROVIDER)` |
| **Used by** | `load_provider()` | Only consumer in codebase |
| **Documented** | `docs/narration_architecture.md` | Yes |
| **Readme.md** | — | **Not documented** |

### 3.2 Default Behavior

When `NARRATOR_PROVIDER` is unset:

1. `load_provider()` reads env, falls back to `"piper"`
2. Lazy-imports `PiperProvider`
3. Returns configured `PiperProvider` instance
4. Unknown provider names raise `NarratorNotFoundError`

### 3.3 Related Piper-Only Env Var

| Variable | Consumed in | Scope |
|----------|-------------|-------|
| `PIPER_EXECUTABLE` | `piper_provider.py:32` | Piper provider only |

**Verdict:** **PASS** — `NARRATOR_PROVIDER` is implemented with correct default. **Gap:** not yet documented in `Readme.md`.

---

## 4. Backward Compatibility

### 4.1 Output Contract: `audio/output.wav`

| Module | Constant / Reference | Line | Role |
|--------|---------------------|------|------|
| `backend/services/narration/narration_manager.py` | `DEFAULT_OUTPUT_PATH` | 17 | Narration output default |
| `voice_generator.py` | `OUTPUT_PATH` | 25 | Facade default |
| `caption_generator.py` | `AUDIO_PATH` | 25 | Caption duration + Whisper input |
| `agents/scene_agent.py` | `AUDIO_PATH` | 22 | Scene duration probing |
| `agents/visual_timeline_agent.py` | `AUDIO_PATH` | 60 | FFmpeg audio mux |
| `agents/timeline_video_builder.py` | `AUDIO_PATH` | 25 | Legacy renderer (shared helpers) |
| `video_generator.py` | `AUDIO_PATH` | 16 | Legacy/unused renderer |

### 4.2 Downstream Modules — Change Required?

| Module | Modified in Phase 1.2? | Still reads `audio/output.wav`? |
|--------|------------------------|--------------------------------|
| `caption_generator.py` | No | Yes |
| `agents/scene_agent.py` | No | Yes |
| `agents/visual_timeline_agent.py` | No | Yes |
| `agents/timeline_video_builder.py` | No | Yes |
| `video_generator.py` | No | Yes |
| `frontend/**` | No | N/A (no audio path logic) |

### 4.3 Public API Preserved

| Entry point | Before | After | Status |
|-------------|--------|-------|--------|
| `VoiceGenerator().generate()` | Returns `Path` to WAV | Same | **Unchanged** |
| `main.py` Phase 2 | `voice_generator.generate()` | Same | **Unchanged** |
| `pipeline_runner._phase_voice()` | `VoiceGenerator().generate()` | Same | **Unchanged** |
| Constructor signature | Piper-specific kwargs | Same kwargs forwarded | **Unchanged** |

**Verdict:** **PASS** — `audio/output.wav` remains the sole output contract; no downstream module requires changes.

---

## 5. Pipeline Verification

### 5.1 End-to-End Flow

```
┌─────────────────────────────────────────────────────────────────────────┐
│ 1. SCRIPT                                                                │
│    script_generator.py :: ScriptGenerator.generate_and_save() / .save() │
│    Output: scripts/script.txt                                            │
└───────────────────────────────────┬─────────────────────────────────────┘
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ 2. NARRATION MANAGER                                                     │
│    main.py:159 / pipeline_runner._phase_voice():248                     │
│      → voice_generator.VoiceGenerator.generate()                        │
│        → narration_manager.NarrationManager.generate()                  │
│           • _read_script()                                               │
│           • text_utils.prepare_narration_text()                          │
│           • provider.generate_audio(text, "audio/output.wav")            │
│    Output: audio/output.wav                                              │
└───────────────────────────────────┬─────────────────────────────────────┘
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ 3. PROVIDER                                                              │
│    piper_provider.PiperProvider.generate_audio()                          │
│      • subprocess → piper.exe → WAV                                      │
└───────────────────────────────────┬─────────────────────────────────────┘
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ 4. CAPTION GENERATION                                                    │
│    caption_generator.CaptionGenerator.generate()                         │
│      • _verify_audio() on audio/output.wav                               │
│      • _probe_audio_duration() via ffprobe                               │
│      • segment_captions_from_script() or Whisper fallback                │
│    Output: captions/output.srt                                           │
└───────────────────────────────────┬─────────────────────────────────────┘
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ 5. SCENE GENERATION (parallel concern — uses audio duration)             │
│    scene_agent.SceneAgent.generate()                                     │
│      • probe_audio_duration(audio/output.wav)                            │
│    Output: scenes/scenes.json                                            │
└───────────────────────────────────┬─────────────────────────────────────┘
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ 6. VIDEO RENDERING                                                       │
│    visual_timeline_agent.VisualTimelineAgent.generate()                  │
│      • _read_narration_duration() — probes audio/output.wav            │
│      • _build_visual_timeline()                                          │
│      • _finalize_with_audio_and_subtitles()                              │
│        FFmpeg: visual MP4 + audio/output.wav → videos/output.mp4        │
│        Audio encode: AAC 192k, 48 kHz                                    │
│    Output: videos/output.mp4                                             │
└─────────────────────────────────────────────────────────────────────────┘
```

### 5.2 Function Call Chain (Voice Phase)

| Step | File | Function |
|------|------|----------|
| CLI entry | `main.py` | `main()` → `voice_generator.generate()` |
| API entry | `backend/pipeline_runner.py` | `_phase_voice()` → `VoiceGenerator().generate()` |
| Facade | `voice_generator.py` | `VoiceGenerator.generate()` → `NarrationManager.generate()` |
| Orchestration | `narration_manager.py` | `NarrationManager.generate()` |
| Provider load | `narration_manager.py` | `load_provider()` |
| Synthesis | `piper_provider.py` | `PiperProvider.generate_audio()` |

### 5.3 Function Call Chain (Post-Voice)

| Phase | File | Function | Reads `audio/output.wav`? |
|-------|------|----------|---------------------------|
| Captions | `caption_generator.py` | `CaptionGenerator.generate()` | Yes |
| Scenes | `agents/scene_agent.py` | `SceneAgent._analyze_duration()` → `probe_audio_duration()` | Yes |
| Video | `agents/visual_timeline_agent.py` | `_read_narration_duration()`, `_finalize_with_audio_and_subtitles()` | Yes |

**Verdict:** **PASS** — full pipeline trace confirmed; narration abstraction sits correctly between script and downstream consumers.

---

## 6. Architecture Quality Review

### 6.1 Remaining Piper Coupling

| Location | Issue | Severity |
|----------|-------|----------|
| `narration_manager.load_provider()` | Hardcoded `if provider_name == "piper"` branch | Medium — expected until second provider exists |
| `NarrationManager.__init__()` | `piper_executable`, `voice_model`, `voice_config`, `voice_speed` kwargs | Medium — Piper-shaped factory API |
| `voice_generator.py` | Direct import from `piper_provider` for constant re-exports | Low — backward-compat facade |
| `voice_generator.VoiceGenerator.__init__()` | `piper_executable` parameter name | Low — legacy API surface |
| `Readme.md` | Documents Piper only; no `NARRATOR_PROVIDER` | Low — documentation gap |
| `docs/voice_pipeline_audit.md` | Stale claims (e.g. Piper in `main.py`) | Low — doc drift |

### 6.2 Hardcoded Paths

| Path | Occurrences | Centralized? |
|------|-------------|--------------|
| `audio/output.wav` | 7 modules | No — duplicated `AUDIO_PATH` / `OUTPUT_PATH` constants |
| `scripts/script.txt` | `narration_manager.py`, `caption_generator.py`, `script_generator.py` | No |
| `models/piper/en_US-ryan-high.onnx` | `piper_provider.py` only | Acceptable (provider-scoped) |
| `C:/Tools/piper/piper.exe` | `piper_provider.py` only | Acceptable (provider-scoped) |
| `videos/output.mp4` | `visual_timeline_agent.py` | Unchanged (video contract) |

### 6.3 Potential Issues Before Kokoro Integration

| # | Issue | Recommendation |
|---|-------|----------------|
| 1 | No `kokoro` branch in `load_provider()` | Add `KokoroProvider` + register in factory (Phase 1.3) |
| 2 | Factory kwargs are Piper-specific | Introduce `ProviderConfig` dict or provider-specific env vars (`KOKORO_*`) |
| 3 | No WAV normalization layer | If Kokoro outputs non-WAV, add conversion inside provider before returning |
| 4 | `verify_resources()` message says "Verifying voice model..." | Generic message or provider-driven step labels |
| 5 | No automated tests for abstraction layer | Add unit tests for `load_provider()`, mock `NarratorProvider` |
| 6 | `NARRATOR_PROVIDER` not in Readme / `.env` example | Document before release |
| 7 | Single-provider progress strings reference provider `name` | Already dynamic (`Generating narration ({name})...`) — OK |

### 6.4 Recommended Cleanup Tasks (Phase 1.3 prep)

1. **Add `KokoroProvider`** implementing `NarratorProvider.generate_audio()`
2. **Refactor `load_provider()`** — use registry dict instead of `if/elif` chain
3. **Generalize `NarrationManager` kwargs** — replace `piper_executable` with `**provider_options` or env-only config per provider
4. **Update `Readme.md`** — document `NARRATOR_PROVIDER`, remove Piper-only framing in feature table
5. **Update or archive `docs/voice_pipeline_audit.md`** — mark as pre-1.2 historical
6. **Optional:** centralize `AUDIO_PATH` constant in shared `paths.py` (low priority; not blocking)
7. **Optional:** deprecate `voice.generator.py` compat shim over time

---

## 7. Final Verdict

### Criteria Scorecard

| Criterion | Result | Rationale |
|-----------|--------|-----------|
| **Provider Isolation** | **PASS** | Piper runtime logic confined to `piper_provider.py`; orchestration/API/UI/renderer clean; legacy alias only in facade |
| **Environment-based Provider Selection** | **PASS** | `NARRATOR_PROVIDER` implemented with `piper` default; consumed in `load_provider()` |
| **Backward Compatibility** | **PASS** | `audio/output.wav` unchanged; `VoiceGenerator` API unchanged; zero downstream modifications |
| **Production Readiness** | **PASS with caveats** | Architecture is sound and pipeline-preserving; gaps: no unit tests, Readme not updated, residual factory coupling |
| **Ready for Phase 1.3 Kokoro Integration** | **PASS with conditions** | Abstraction layer is sufficient; Kokoro requires new provider class + factory registration + provider-specific config |

### Overall: **PASS**

Phase 1.2 achieves its stated goal: AutoShorts can add a second voice engine without modifying captions, scenes, video rendering, API, or UI. The narration system is **ready for Kokoro integration** with the documented factory and config cleanup tasks above.

### Conditions for Phase 1.3

Before merging Kokoro as a production option:

- [ ] Implement `KokoroProvider(NarratorProvider)` writing WAV to `audio/output.wav`
- [ ] Register `kokoro` in `load_provider()`
- [ ] Define Kokoro-specific env vars (e.g. `KOKORO_MODEL_PATH`, `KOKORO_VOICE`)
- [ ] Verify ffprobe/FFmpeg/Whisper compatibility with Kokoro WAV output
- [ ] Document `NARRATOR_PROVIDER=kokoro` in `Readme.md`
- [ ] Add at least smoke test: mock provider → `NarrationManager.generate()` → output file exists

---

## Appendix A: Stale Documentation Note

`docs/voice_pipeline_audit.md` (Phase 1.1) contains outdated claims:

- Piper logic in `voice_generator.py` — **now moved** to `piper_provider.py`
- `PiperNotFoundError` in `main.py` / `pipeline_runner.py` — **now uses** `NarratorNotFoundError`
- Monolithic `VoiceGenerator` — **now a facade**

Refer to `docs/narration_architecture.md` for current architecture.

---

## Appendix B: Files Created in Phase 1.2

```
backend/services/
├── __init__.py
└── narration/
    ├── __init__.py
    ├── exceptions.py
    ├── narrator_provider.py
    ├── narration_manager.py
    ├── text_utils.py
    └── providers/
        ├── __init__.py
        └── piper_provider.py
```

---

*End of Phase 1.2 Verification Audit*
