# Clip Intelligence Infrastructure (Phase 3.5)

Infrastructure for AI-powered clip understanding. **Florence-2 is not integrated yet** — every collected clip gets placeholder timeline metadata that future phases will populate.

## Flow

```
Downloaded Clip (assets/library/...)
        ↓
Clip Intelligence (ClipAnalyzer)
        ↓
Timeline Metadata (assets/library/metadata/{clip_id}.timeline.json)
        ↓
Generation pipeline (ignores metadata for now)
```

## Package

`backend/services/clip_intelligence/`

| Module | Role |
|--------|------|
| `models.py` | `ClipAnalysis`, `TimelineSegment` dataclasses |
| `metadata_store.py` | Read/write `{clip_id}.timeline.json` |
| `timeline_builder.py` | Build placeholder segment lists |
| `keyframe_extractor.py` | Stub for future frame extraction |
| `clip_analyzer.py` | `ClipAnalyzer` — `analyze()`, `save()`, `load()`, `exists()` |

## Data models

### ClipAnalysis

| Field | Description |
|-------|-------------|
| `clip_id` | Asset id (e.g. `pexels_12345`) |
| `provider` | Source provider name |
| `duration` | Clip length in seconds |
| `resolution` | e.g. `1080x1920` |
| `orientation` | `portrait` or `landscape` |
| `timeline_segments` | List of `TimelineSegment` |

### TimelineSegment

| Field | Description |
|-------|-------------|
| `start_time` | Segment start (seconds) |
| `end_time` | Segment end (seconds) |
| `description` | Content description (`Unknown` in Phase 3.5) |
| `objects` | Detected objects (`[]` in Phase 3.5) |
| `confidence` | Model confidence (`0` in Phase 3.5) |

## On-disk format

Path: `assets/library/metadata/{clip_id}.timeline.json`

Example (placeholder):

```json
{
  "clip_id": "pexels_12345",
  "provider": "pexels",
  "duration": 12.5,
  "resolution": "1080x1920",
  "orientation": "portrait",
  "timeline_segments": [
    {
      "start_time": 0.0,
      "end_time": 12.5,
      "description": "Unknown",
      "objects": [],
      "confidence": 0.0
    }
  ],
  "local_path": "assets/library/Space/Rocket Launch/pexels_12345.mp4",
  "analyzed_at": "2026-06-24T12:00:00+00:00",
  "ai_engine": "placeholder"
}
```

## ClipAnalyzer API

```python
from backend.services.clip_intelligence import ClipAnalyzer

analyzer = ClipAnalyzer()

analysis = analyzer.analyze(
    clip_id="pexels_12345",
    provider="pexels",
    local_path="assets/library/.../pexels_12345.mp4",
    width=1080,
    height=1920,
    duration=12.5,
)
analyzer.save(analysis)

loaded = analyzer.load("pexels_12345")
exists = analyzer.exists("pexels_12345")
```

`analyze_and_save()` combines analyze + save (used by the collection engine).

## Asset Collection integration

`LibraryStorage.store()` calls `ClipAnalyzer.analyze_and_save()` after each successful download. Failures are logged but do not block the download.

The **video generation pipeline** (`VisualTimelineAgent`) is unchanged and does not read timeline metadata.

## Next phase (Florence-2)

1. Implement `KeyframeExtractor.extract()` with FFmpeg.
2. Run Florence-2 on keyframes inside `ClipAnalyzer.analyze()`.
3. Populate `description`, `objects`, and `confidence` per segment.
4. Optionally consume timeline metadata during clip ranking or scene matching.

## Related docs

- [Asset Collection](asset_collection.md)
- [AutoShorts v2 Architecture](autoshorts_v2_architecture.md)
