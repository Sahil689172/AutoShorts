# Kokoro TTS Feasibility Research — Phase 1.3A

**Date:** 2026-06-24  
**Target hardware:** Intel Core i7-1255U, 16 GB RAM, Windows 11, CPU-only  
**Constraint:** No production code modified — research only  
**AutoShorts context:** Provider abstraction layer (Phase 1.2) with `audio/output.wav` contract  

---

## Executive Summary

**Recommended implementation:** [`kokoro-onnx`](https://pypi.org/project/kokoro-onnx/) (PyPI package by [thewh1teagle/kokoro-onnx](https://github.com/thewh1teagle/kokoro-onnx))

**Recommended model:** `kokoro-v1.0.onnx` + `voices-v1.0.bin` (English US voice e.g. `af_heart`)

Kokoro integrates cleanly with AutoShorts' existing provider architecture: pure Python + ONNX Runtime (no PyTorch), CPU-native, writes standard WAV via `soundfile`, and mirrors the Piper pattern (local model files under `models/`). On the target i7-1255U, expect **~15–30 seconds** of synthesis time for a typical 80–100 word Shorts script (30–45 s of audio), which is acceptable for batch pipeline use.

**Feasibility verdict:** **GO** — proceed to Phase 1.3B (`KokoroProvider` implementation).

---

## 1. Implementation Landscape

### Candidates Evaluated

| Implementation | Type | Windows CPU | ONNX | pip install | Verdict |
|----------------|------|-------------|------|-------------|---------|
| **[kokoro-onnx](https://github.com/thewh1teagle/kokoro-onnx)** | Python + ONNX Runtime | Yes | Yes | `pip install kokoro-onnx` | **Recommended** |
| [hexgrad/kokoro](https://github.com/hexgrad/kokoro) | PyTorch pipeline | Problematic | No (native) | `pip install kokoro` | Reject — heavy deps, espeak friction |
| [fastkokoro](https://pypi.org/project/fastkokoro/) | ONNX server library | Yes | Yes | `pip install fastkokoro[cpu]` | Reject — server-oriented, less mature for pipeline embedding |
| [Kokoros](https://github.com/lucasjinreal/Kokoros) | Rust | Via bindings | Yes | N/A | Reject — not Python-native |
| CLI / subprocess wrappers | External binary | Varies | Varies | Manual | Reject — no mature Windows Kokoro CLI equivalent to Piper |

### Why `kokoro-onnx` Wins

1. **Same integration pattern as Piper** — local model files + Python subprocess/library call → WAV file
2. **ONNX Runtime CPU** — aligns with AutoShorts' existing ONNX mental model (Piper uses ONNX models)
3. **No PyTorch** — avoids multi-GB torch install and Windows compilation issues (spaCy/blis, AVX flags)
4. **Active maintenance** — ~2,600 GitHub stars, PyPI v0.5.0 (Jan 2026), MIT license (wrapper) + Apache 2.0 (model weights)
5. **Fits `NarratorProvider.generate_audio(text, output_path)`** — returns WAV path after `soundfile.write()`
6. **English-first** — v1.0 model + 26 voices in `voices-v1.0.bin`; ideal for current English-only Shorts pipeline

---

## 2. Recommended Package & Model

### Package (single recommendation)

```
kokoro-onnx >= 0.5.0
soundfile >= 0.12.0
```

Transitive dependencies (installed automatically):

| Package | Version constraint | Purpose |
|---------|-------------------|---------|
| `onnxruntime` | >= 1.20.1 | CPU inference (default `CPUExecutionProvider`) |
| `numpy` | >= 2.0.2 | Audio array handling |
| `phonemizer-fork` | >= 3.3.2 | G2P / phoneme conversion |
| `espeakng-loader` | >= 0.2.4 | Bundled eSpeak-NG data (reduces Windows install pain) |

Python support: **3.10 – 3.13** (per PyPI; `<3.14`)

### Model (single recommendation for AutoShorts)

| File | Size | Source |
|------|------|--------|
| `kokoro-v1.0.onnx` | ~310 MB (FP32) | [model-files-v1.0 release](https://github.com/thewh1teagle/kokoro-onnx/releases/tag/model-files-v1.0) |
| `voices-v1.0.bin` | ~27 MB | Same release |

**Suggested AutoShorts layout:**

```
models/kokoro/
├── kokoro-v1.0.onnx
└── voices-v1.0.bin
```

**Recommended voice:** `af_heart` (American female, warm — widely used in Kokoro examples)  
**Alternatives:** `af_bella`, `af_sarah`, `am_michael` — see [VOICES.md](https://huggingface.co/hexgrad/Kokoro-82M/blob/main/VOICES.md)

**Speed parameter:** `speed=1.0` default; map from AutoShorts `voice_speed` (Piper uses `length_scale=1.25` — values are not 1:1 equivalent; tune empirically).

### Model variants not recommended (for initial integration)

| Variant | Size | Notes |
|---------|------|-------|
| `kokoro-v1.0.int8.onnx` | ~88 MB | Faster, lower quality — consider later as optional speed tier |
| `kokoro-v1.0.fp16.onnx` | ~169 MB | Minimal benefit on CPU without FP16 acceleration |
| `kokoro-v1.1-zh.onnx` | Separate | Chinese-focused; adds `misaki[zh]` dependency — out of scope for English Shorts v1 |

---

## 3. Installation

### Step 1 — Python packages

```powershell
# From AutoShorts project root (venv active)
pip install "kokoro-onnx>=0.5.0" "soundfile>=0.12.0"
```

Optional dev verification in isolated environment:

```powershell
pip install uv
uv init -p 3.12 kokoro-test
cd kokoro-test
uv add kokoro-onnx soundfile
```

### Step 2 — Download model files

```powershell
mkdir models\kokoro
cd models\kokoro

# PowerShell
Invoke-WebRequest -Uri "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx" -OutFile "kokoro-v1.0.onnx"
Invoke-WebRequest -Uri "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin" -OutFile "voices-v1.0.bin"
```

### Step 3 — Windows eSpeak fallback (if phonemizer fails)

`espeakng-loader` bundles data for most setups. If you see `RuntimeError: espeak not installed on your system`:

1. Install [eSpeak NG MSI](https://github.com/espeak-ng/espeak-ng/releases/download/1.52.0/espeak-ng.msi)
2. Set env vars **before** importing `kokoro_onnx`:

```python
import os
os.environ["PHONEMIZER_ESPEAK_LIBRARY"] = r"C:\Program Files\eSpeak NG\libespeak-ng.dll"
os.environ["PHONEMIZER_ESPEAK_PATH"] = r"C:\Program Files\eSpeak NG"
```

3. Ensure `phonemizer` (non-fork) is **not** installed alongside `phonemizer-fork` — uninstall both and reinstall only `phonemizer-fork` if conflicts occur ([issue #111](https://github.com/thewh1teagle/kokoro-onnx/issues/111)).

### Step 4 — requirements.txt (future Phase 1.3B)

```
kokoro-onnx>=0.5.0
soundfile>=0.12.0
```

`onnxruntime` is pulled transitively. Do **not** install `onnxruntime-gpu` on CPU-only systems.

---

## 4. Sample Code

### Minimal synthesis (matches upstream `examples/save.py`)

```python
"""Proof-of-concept — NOT production code."""
from pathlib import Path

import soundfile as sf
from kokoro_onnx import Kokoro

MODEL = Path("models/kokoro/kokoro-v1.0.onnx")
VOICES = Path("models/kokoro/voices-v1.0.bin")
OUTPUT = Path("audio/output.wav")

text = (
    "Did you know octopuses have three hearts? "
    "Two pump blood to the gills, and one pumps it to the rest of the body."
)

kokoro = Kokoro(str(MODEL), str(VOICES))
samples, sample_rate = kokoro.create(
    text,
    voice="af_heart",
    speed=1.0,
    lang="en-us",
)

OUTPUT.parent.mkdir(parents=True, exist_ok=True)
sf.write(str(OUTPUT), samples, sample_rate)
print(f"Wrote {OUTPUT} ({sample_rate} Hz, {len(samples)} samples)")
```

### Proposed `KokoroProvider` sketch (Phase 1.3B)

```python
"""Illustrative — matches NarratorProvider contract."""
from pathlib import Path

import numpy as np
import soundfile as sf
from kokoro_onnx import Kokoro

from backend.services.narration.exceptions import NarrationError, NarratorNotFoundError
from backend.services.narration.narrator_provider import NarratorProvider


class KokoroProvider(NarratorProvider):
    def __init__(
        self,
        model_path: Path = Path("models/kokoro/kokoro-v1.0.onnx"),
        voices_path: Path = Path("models/kokoro/voices-v1.0.bin"),
        voice: str = "af_heart",
        speed: float = 1.0,
        lang: str = "en-us",
    ) -> None:
        self.model_path = Path(model_path)
        self.voices_path = Path(voices_path)
        self.voice = voice
        self.speed = speed
        self.lang = lang
        self._engine: Kokoro | None = None

    @property
    def name(self) -> str:
        return "kokoro"

    def verify_installation(self) -> None:
        try:
            import kokoro_onnx  # noqa: F401
        except ImportError as exc:
            raise NarratorNotFoundError(
                "kokoro-onnx is not installed. Run: pip install kokoro-onnx soundfile"
            ) from exc

    def verify_resources(self) -> None:
        if not self.model_path.is_file():
            raise NarrationError(f"Kokoro model not found: {self.model_path}")
        if not self.voices_path.is_file():
            raise NarrationError(f"Kokoro voices not found: {self.voices_path}")

    def verify_prerequisites(self) -> None:
        self.verify_installation()
        self.verify_resources()

    def _get_engine(self) -> Kokoro:
        if self._engine is None:
            self._engine = Kokoro(str(self.model_path), str(self.voices_path))
        return self._engine

    def generate_audio(self, text: str, output_path: str) -> str:
        engine = self._get_engine()
        try:
            samples, sample_rate = engine.create(
                text, voice=self.voice, speed=self.speed, lang=self.lang
            )
        except Exception as exc:
            raise NarrationError(f"Kokoro synthesis failed: {exc}") from exc

        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        sf.write(str(out), samples, sample_rate)
        return str(out.resolve())
```

### Sentence chunking (recommended for provider hardening)

AutoShorts scripts are 80–100 words (~400–600 characters) with punctuation — usually one safe chunk. For robustness, chunk by sentence before concatenation:

```python
import re
import numpy as np


def synthesize_chunked(kokoro, text: str, voice: str, speed: float, lang: str):
    """Split on sentence boundaries; concat audio with brief silence."""
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    segments = []
    sample_rate = 24_000
    for sentence in sentences:
        if not sentence.strip():
            continue
        samples, sample_rate = kokoro.create(
            sentence, voice=voice, speed=speed, lang=lang
        )
        segments.append(samples)
        segments.append(np.zeros(int(sample_rate * 0.15), dtype=samples.dtype))  # 150ms pause
    return np.concatenate(segments), sample_rate
```

---

## 5. Performance on Intel i7-1255U

### Hardware profile

| Spec | i7-1255U |
|------|----------|
| Cores | 10 (2 P-cores + 8 E-cores) |
| Threads | 12 |
| Base / boost | 1.7 / 4.7 GHz (P-core) |
| RAM | 16 GB (target system) |
| GPU | Intel Iris Xe (not used — CPU-only path) |

### Benchmark reference (CPU, no GPU)

Source: [Kokoro 82M CPU TTS Benchmark](https://heyneo.com/blog/kokoro-supertonic-inflect-nano-cpu-tts-benchmark) (Jun 2026)  
Hardware: Intel Xeon 4-core, 15.6 GB RAM, `kokoro-onnx` 0.5.0, `onnxruntime` CPU.

| Metric | Kokoro-82M ONNX |
|--------|-----------------|
| Mean RTF | **0.57** (1.8× faster than real-time on average) |
| Long text (~483 chars) wall time | **~15.7 s** |
| Paragraph (~851 chars) wall time | **~26.5 s** |
| Extended (~1712 chars) wall time | **~68 s** |
| UTMOS quality score | **4.44 / 5** |

### AutoShorts workload estimate

| Script profile | Chars | Expected audio | Est. synthesis (i7-1255U) |
|----------------|-------|----------------|---------------------------|
| Typical Shorts script | 400–600 | 30–45 s | **12–25 s** |
| Max script (100 words) | ~650 | ~40–50 s | **18–30 s** |

The i7-1255U has **3× the threads** of the benchmark Xeon (12 vs 4), so real-world performance may be **equal or better**, though E-core latency varies.

### Memory footprint

| Component | RAM |
|-----------|-----|
| `kokoro-v1.0.onnx` loaded | ~300–500 MB |
| ONNX Runtime overhead | ~200–400 MB |
| Python + numpy buffers | ~100–200 MB |
| **Total during synthesis** | **~1–2 GB** |

Comfortable within 16 GB alongside Ollama, Whisper, and FFmpeg.

### Comparison to current Piper

| Aspect | Piper (current) | Kokoro-onnx (proposed) |
|--------|---------------|------------------------|
| Integration | External `piper.exe` subprocess | In-process Python library |
| Model size | ~50–100 MB (single voice ONNX) | ~337 MB (model + voices) |
| Dependency | Manual binary install | pip install |
| CPU speed | Word-count timeout heuristic | Faster than real-time (RTF ~0.5–0.7) |
| Voice quality | Good (Ryan high) | Higher UTMOS (~4.44) in benchmarks |
| Windows friction | DLL + VC++ redistributable | eSpeak / phonemizer edge cases |

---

## 6. WAV Output & Pipeline Compatibility

### Kokoro audio format

| Property | Value |
|----------|-------|
| Container | WAV (via `soundfile`) |
| Sample rate | **24,000 Hz** |
| Channels | Mono |
| Dtype | float32 → PCM in WAV |
| Bit depth | Typically 16-bit PCM output from soundfile |

### ffprobe compatibility — **COMPATIBLE**

AutoShorts uses ffprobe for duration probing:

```python
# agents/timeline_video_builder.py :: probe_duration()
# agents/scene_agent.py :: probe_audio_duration()
```

ffprobe reads standard WAV at any sample rate. **No changes required.**

### FFmpeg compatibility — **COMPATIBLE**

`VisualTimelineAgent._finalize_with_audio_and_subtitles()` muxes narration:

```
-i audio/output.wav → AAC 192k, -ar 48000
```

FFmpeg automatically resamples 24 kHz → 48 kHz during mux. **No changes required.**

### Whisper compatibility — **COMPATIBLE**

`CaptionGenerator` uses Whisper as fallback (`openai-whisper`). Whisper accepts 24 kHz WAV natively (internally resamples to 16 kHz). Script-timed captions (default path) only need duration from ffprobe — **unaffected**.

### Caption timing compatibility — **COMPATIBLE**

`segment_captions_from_script()` distributes word timings proportionally across **probed audio duration**. Any valid WAV with correct duration works regardless of sample rate.

### Scene agent compatibility — **COMPATIBLE**

`SceneAgent._analyze_duration()` prefers `probe_audio_duration(audio/output.wav)`. Same contract as Piper.

### Contract check

| Requirement | Piper today | Kokoro |
|-------------|-------------|--------|
| Output path `audio/output.wav` | Yes | Yes (via `generate_audio` path arg) |
| Non-empty file | Yes | Yes |
| ffprobe-readable | Yes | Yes |
| FFmpeg-muxable | Yes | Yes |
| Whisper-transcribable | Yes | Yes |

**Pipeline compatibility verdict:** **FULLY COMPATIBLE** — no downstream module changes needed if Kokoro writes valid WAV to `audio/output.wav`.

---

## 7. Risks & Mitigations

| Risk | Severity | Mitigation |
|------|----------|------------|
| **eSpeak / phonemizer Windows errors** | Medium | `espeakng-loader` bundled; fallback to eSpeak NG MSI + env vars; pin `phonemizer-fork` only |
| **510 phoneme limit** | Low–Medium | AutoShorts scripts are short (~80–100 words); add sentence chunking in `KokoroProvider` |
| **Phoneme truncation bugs** (v0.5.0) | Low | Chunk text < 400 chars per call; pin `kokoro-onnx>=0.5.0`; monitor [issue #184](https://github.com/thewh1teagle/kokoro-onnx/issues/184) |
| **numpy >= 2.0.2** dependency | Low | Test with existing `openai-whisper` stack; pin numpy if conflicts arise |
| **First-run model download** | Low | Ship models under `models/kokoro/`; document manual download (gitignored like Piper) |
| **Speed param semantics differ from Piper** | Low | Map `voice_speed` separately per provider; document `speed=1.0` as Kokoro default |
| **Cold-start latency** | Low | Lazy-load `Kokoro` session once per job; optional warmup in provider |
| **RAM pressure with Ollama + Whisper concurrent** | Low | Voice phase runs sequentially in pipeline — no overlap |
| **No GPU acceleration on Iris Xe** | Info | CPU path is sufficient for Shorts-length scripts |
| **License** | Info | kokoro-onnx MIT; Kokoro-82M weights Apache 2.0 — compatible with commercial use |

---

## 8. Environment Variables (Proposed for Phase 1.3B)

| Variable | Default | Purpose |
|----------|---------|---------|
| `NARRATOR_PROVIDER` | `piper` | Set to `kokoro` to switch engine |
| `KOKORO_MODEL_PATH` | `models/kokoro/kokoro-v1.0.onnx` | ONNX model path |
| `KOKORO_VOICES_PATH` | `models/kokoro/voices-v1.0.bin` | Voice embeddings |
| `KOKORO_VOICE` | `af_heart` | Voice ID |
| `KOKORO_SPEED` | `1.0` | Speech rate |
| `KOKORO_LANG` | `en-us` | Language code |
| `PHONEMIZER_ESPEAK_LIBRARY` | (optional) | Windows eSpeak DLL path |
| `PHONEMIZER_ESPEAK_PATH` | (optional) | Windows eSpeak install path |

---

## 9. Integration Checklist (Phase 1.3B Preview)

- [ ] Create `backend/services/narration/providers/kokoro_provider.py`
- [ ] Register `kokoro` in `load_provider()` inside `narration_manager.py`
- [ ] Add `kokoro-onnx` + `soundfile` to `requirements.txt`
- [ ] Document model download in `Readme.md`
- [ ] Add `models/kokoro/` to `.gitignore` (if not already covered by `models/`)
- [ ] Implement sentence chunking for long-text safety
- [ ] Smoke test: `NARRATOR_PROVIDER=kokoro` → `audio/output.wav` → full pipeline → `videos/output.mp4`
- [ ] Verify ffprobe duration matches expected ~30–45 s for typical script

---

## 10. Single Recommendation

### Use `kokoro-onnx` with `kokoro-v1.0.onnx` + `voices-v1.0.bin`

| Criterion | Assessment |
|-----------|------------|
| Windows support | Strong (pip wheels + espeakng-loader) |
| Python integration | Native — fits `NarratorProvider` |
| CPU inference | ONNX Runtime default; RTF ~0.5–0.7 |
| ONNX | Yes — same family as Piper |
| WAV output | Yes — 24 kHz via soundfile |
| AutoShorts pipeline | Fully compatible — `audio/output.wav` unchanged |
| i7-1255U / 16 GB | Comfortable — ~12–30 s per Shorts script |
| Maintenance | Active (2.6k stars, PyPI releases through 2026) |

**Do not use** `hexgrad/kokoro` (PyTorch) for AutoShorts — heavier, harder Windows setup, no advantage over ONNX path on CPU.

---

## 11. References

- [thewh1teagle/kokoro-onnx](https://github.com/thewh1teagle/kokoro-onnx) — recommended package
- [kokoro-onnx on PyPI](https://pypi.org/project/kokoro-onnx/)
- [model-files-v1.0 release](https://github.com/thewh1teagle/kokoro-onnx/releases/tag/model-files-v1.0)
- [hexgrad/Kokoro-82M on Hugging Face](https://huggingface.co/hexgrad/Kokoro-82M)
- [Kokoro CPU benchmark (Jun 2026)](https://heyneo.com/blog/kokoro-supertonic-inflect-nano-cpu-tts-benchmark)
- [AutoShorts narration architecture](narration_architecture.md)
- [AutoShorts Phase 1.2 verification](phase_1_2_verification.md)

---

*End of Phase 1.3A Kokoro Feasibility Research*
