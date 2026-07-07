# Florence-2 Clip Intelligence (Phase 3.6)

Integrates **Florence-2** into the Clip Intelligence subsystem to automatically generate timeline metadata **for every newly downloaded clip**.

The **generation pipeline is not modified** in this phase. Timeline metadata is generated at collection time and stored for future retrieval.

---

## Flow

```
Downloaded Clip
    ↓
PySceneDetect (shot detection)
    ↓
One representative keyframe per shot
    ↓
Florence-2 (caption + object detection)
    ↓
Timeline segments JSON
    ↓
assets/library/metadata/{clip_id}.timeline.json
```

---

## Key modules

### `backend/services/clip_intelligence/florence_provider.py`

**Responsibilities**

- Loads Florence-2 once (lazy load on first call).
- Accepts a **PIL Image**.
- Returns:
  - `description`
  - `objects`
  - `confidence`

Notes:

- Florence outputs are post-processed via the Florence processor.
- Florence doesn’t always provide calibrated per-object scores; `confidence` is a **deterministic heuristic** used for now.
- The model id comes from a single configuration point (see below); it is **not** hardcoded in the provider.

---

## Vision model configuration (Phase 3.6D)

The vision model is defined in **one place**:

`backend/services/clip_intelligence/config.py`

```python
DEFAULT_VISION_MODEL = "microsoft/Florence-2-base"
VISION_MODEL_ENV = "VISION_MODEL"
```

Resolution order:

1. `VISION_MODEL` environment variable (if set)
2. `DEFAULT_VISION_MODEL` (`microsoft/Florence-2-base`)

On first analysis the provider logs a startup line:

```
Vision Model: microsoft/Florence-2-base
```

### Why Base is the default

- **Faster CPU inference** — Florence-2 Base (~0.23B params) runs roughly 2–3× faster than Large (~0.77B) on CPU, which is the common AutoShorts environment.
- **Lower memory** — Base loads with a smaller footprint, reducing the chance of OOM during collection.
- **Caption quality is sufficient** — For short-form clip tagging (captions + object labels used for future retrieval), Base produces adequate descriptions; the marginal quality gain from Large does not justify the CPU cost at collection time.

### How to switch to Large

Set the environment variable — no code changes:

```bash
# Windows (PowerShell)
$env:VISION_MODEL = "microsoft/Florence-2-large"

# macOS / Linux
export VISION_MODEL=microsoft/Florence-2-large
```

Or add it to your `.env` file:

```
VISION_MODEL=microsoft/Florence-2-large
```

The same variable is honored by `tools/test_florence.py`, so smoke tests use the same model as the pipeline. You can still override per run:

```bash
python tools/test_florence.py image.jpg --model microsoft/Florence-2-large
```

### Expected performance differences

| Model | Params | Relative CPU speed | Caption quality | Default |
|-------|--------|--------------------|-----------------|---------|
| `microsoft/Florence-2-base` | ~0.23B | Faster (baseline) | Good for tagging | ✅ |
| `microsoft/Florence-2-large` | ~0.77B | ~2–3× slower on CPU | Higher detail | Opt-in |

Exact timings depend on CPU, clip length, and shot count (one Florence pass per detected shot).

### `backend/services/clip_intelligence/keyframe_extractor.py`

**Responsibilities**

- Uses **PySceneDetect** to split clips into shots.
- Extracts **one representative frame per shot** (midpoint timestamp) using OpenCV.
- Returns keyframes as PIL images + timestamps.

### `backend/services/clip_intelligence/clip_analyzer.py`

**Responsibilities**

- Orchestrates shot detection → keyframe extraction → Florence analysis.
- Builds timeline segments.
- Saves timeline JSON via `MetadataStore`.
- **Never fails collection**:
  - If PySceneDetect or Florence fails, it falls back to placeholder metadata.

---

## Timeline JSON format (Phase 3.6)

Stored at:

`assets/library/metadata/{clip_id}.timeline.json`

Format:

```json
[
  {
    "start": 0.0,
    "end": 2.4,
    "description": "…",
    "objects": ["car", "road", "traffic light"],
    "confidence": 0.95
  }
]
```

Backward compatibility:

- Older Phase 3.5 timeline files (object format with `timeline_segments`) are still loadable.

---

## Logging

On first load the provider logs the active model:

```
Vision Model: microsoft/Florence-2-base
```

The analyzer logs (best-effort):

- Clip id
- Shot count
- Analysis time
- Timeline saved path

Collection is never interrupted by Florence errors.

---

## Installation

Added dependencies in `requirements.txt`:

- `transformers`
- `torch`
- `scenedetect[opencv]`
- `opencv-python`

On Windows, installing `torch` may require following the PyTorch install guide for your CUDA / CPU setup.

---

## Next steps (future phases)

- Use actual shot boundaries from PySceneDetect as segment `[start,end]` (instead of timestamp-midpoint reconstruction).
- Persist richer Florence outputs (e.g., boxes) if needed.
- Use timeline metadata for timestamp-based retrieval and scene-to-clip alignment.

