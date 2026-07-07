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

