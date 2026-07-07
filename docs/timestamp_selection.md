# Timestamp-Based Clip Selection (Phase 3.7)

Renders the **most relevant portion** of every selected video clip using Florence-generated timeline metadata, instead of always trimming from the beginning.

The renderer architecture and FFmpeg pipeline are unchanged — only the trim **start** is now chosen intelligently.

---

## Flow

```
Selected clip
    ↓
Load {clip_id}.timeline.json
    ↓
Score each timeline segment against scene context
    ↓
Pick highest-scoring segment
    ↓
Compute trim window (sized to narration)
    ↓
FFmpeg -ss <start> -t <narration>  (existing pipeline)
```

If timeline metadata is missing/empty/placeholder, the pipeline falls back to the previous behavior (trim from `0.0`).

---

## Where it runs

`agents/visual_timeline_agent.py`

- `_render_video_segment()` now calls `_resolve_trim_start(scene)` and injects `-ss <start>` before `-i` when the start is greater than zero.
- Helpers:
  - `_resolve_trim_start()` — probes clip duration, runs selection, logs, returns start seconds.
  - `_timeline_clip_id_candidates()` — maps a scene's selected clip to timeline file id(s) (`{clip_id}` and `{provider}_{clip_id}`).
  - `_scene_tokens()` — builds the scene token set (title, description, queries, extracted objects).

Selection logic lives in:

`backend/services/clip_intelligence/segment_selector.py`

- `select_trim_window(...)` → `TrimSelection | None`
- Returns `None` to signal fallback.

Only **video** scenes use this. Image scenes are unaffected.

---

## Segment scoring

For each timeline segment, a similarity score in `0.0–1.0` is computed by comparing:

| Scene side | Timeline side |
|------------|---------------|
| Scene title + visual description | Segment `description` |
| QueryAgent queries (`scene.queries`, `scene.query`) | Segment `objects` |
| Extracted scene objects (`ExtractedObjects.summary_labels()`) | Segment `description` + `objects` |

Method:

1. Token Jaccard similarity between scene tokens and segment tokens (description + objects).
2. `+0.15` bonus when any segment **object label** overlaps scene tokens.
3. Scaled by segment `confidence`: `jaccard * (0.5 + 0.5 * confidence)`.

The highest-scoring segment wins. If nothing matches (score `0`), the **highest-confidence** segment is used and the reason notes it.

---

## Trim window

Given the winning segment `[seg_start, seg_end]`, the clip `duration`, and the scene's `narration` duration:

- **Window length** = `min(narration, clip_duration)`
- **Centered** on the segment midpoint
- **Clamped** to `[0, clip_duration - window]`

Behavior:

| Condition | Behavior | Reason logged |
|-----------|----------|---------------|
| `narration >= segment length` | Expand the window around the segment, staying within clip bounds | "narration longer than segment; expanded window within clip bounds" |
| `narration < segment length` | Center a shorter window on the segment | "narration shorter than segment; centered window on segment" |

The FFmpeg `-t` remains the scene (narration) duration, so total segment/video length is unchanged.

---

## Fallback (no behavior change)

`select_trim_window()` returns `None` → trim start `0.0` (current behavior) when:

- No timeline file exists for the clip id candidates.
- The timeline file is empty.
- All segments are placeholders (`description == "Unknown"` and no `objects`).

Clip duration probe failure or any selection exception also falls back to `0.0`. Collection/rendering is never blocked.

> Note: timeline metadata is produced by the **offline collector** (`assets/library/metadata/`). Clips fetched directly during generation that were never collected will simply fall back to trim-from-start.

---

## Logging

For each video scene that uses timeline metadata, the pipeline prints:

- Scene
- Selected Clip
- Timeline Segment (index, `[start–end]`, description)
- Trim Start
- Trim End
- Reason
- Similarity Score

Example:

```
  Scene 3 | timeline-based trim
    Selected clip:    pexels_35507232
    Timeline segment: 2/4 [4.20s–7.10s] 'a car driving on a highway'
    Trim start:       3.15s
    Trim end:         8.15s
    Reason:           narration longer than segment; expanded window within clip bounds
    Similarity score: 0.412
```

Scenes without metadata log a single fallback line.

---

## Related docs

- [Florence-2 Clip Intelligence](florence_integration.md)
- [Clip Intelligence Infrastructure](clip_intelligence.md)
- [Object Extraction](object_extraction.md)
