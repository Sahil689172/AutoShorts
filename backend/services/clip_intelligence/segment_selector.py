"""Select the best-matching timeline segment and compute a trim window.

Used by the rendering pipeline (Phase 3.7) to render the most relevant
portion of a clip instead of always trimming from the beginning.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from backend.services.clip_intelligence.metadata_store import MetadataStore
from backend.services.clip_intelligence.models import TimelineSegment


def tokenize(text: str) -> set[str]:
    words = re.findall(r"\w+", (text or "").lower())
    return {w for w in words if len(w) > 2}


@dataclass(frozen=True)
class TrimSelection:
    """Result of timeline-based trim selection."""

    segment: TimelineSegment
    segment_index: int
    segment_count: int
    trim_start: float
    trim_end: float
    score: float
    reason: str


def _score_segment(segment: TimelineSegment, scene_tokens: set[str]) -> float:
    """Similarity between scene context and a timeline segment (0.0–1.0)."""
    seg_tokens = tokenize(segment.description)
    for obj in segment.objects:
        seg_tokens |= tokenize(obj)

    if not scene_tokens or not seg_tokens:
        return 0.0

    intersection = scene_tokens & seg_tokens
    union = scene_tokens | seg_tokens
    jaccard = len(intersection) / len(union) if union else 0.0

    # Bonus for direct object-label overlap (objects are strong signals).
    object_tokens: set[str] = set()
    for obj in segment.objects:
        object_tokens |= tokenize(obj)
    if object_tokens & scene_tokens:
        jaccard = min(1.0, jaccard + 0.15)

    # Weight by the model's own confidence in this segment.
    confidence = max(0.0, min(1.0, segment.confidence))
    return min(1.0, jaccard * (0.5 + 0.5 * confidence))


def _compute_trim_window(
    segment: TimelineSegment,
    clip_duration: float,
    narration_duration: float,
) -> tuple[float, float, str]:
    """Center a trim window on the segment, sized to the narration.

    - narration >= segment length: expand window (proportionally) around the
      segment while staying within clip boundaries.
    - narration <  segment length: center a shorter window on the segment.
    """
    clip_duration = max(0.0, float(clip_duration))
    narration = max(0.0, float(narration_duration))
    seg_start = max(0.0, float(segment.start))
    seg_end = max(seg_start, float(segment.end))
    seg_len = seg_end - seg_start
    seg_center = (seg_start + seg_end) / 2.0

    if clip_duration <= 0:
        return 0.0, narration, "clip duration unknown; trim from segment start"

    window = min(narration, clip_duration) if narration > 0 else min(seg_len, clip_duration)

    start = seg_center - window / 2.0
    start = max(0.0, min(start, clip_duration - window))
    end = min(clip_duration, start + window)

    if narration >= seg_len:
        reason = "narration longer than segment; expanded window within clip bounds"
    else:
        reason = "narration shorter than segment; centered window on segment"
    return start, end, reason


def select_trim_window(
    *,
    clip_id_candidates: list[str],
    clip_duration: float,
    narration_duration: float,
    scene_tokens: set[str],
    metadata_store: MetadataStore | None = None,
) -> TrimSelection | None:
    """Load timeline metadata and pick the best segment + trim window.

    Returns None when no (non-placeholder) timeline metadata is available,
    signalling the caller to fall back to current trim-from-start behavior.
    """
    store = metadata_store or MetadataStore()

    segments: list[TimelineSegment] | None = None
    for clip_id in clip_id_candidates:
        if not clip_id:
            continue
        loaded = store.load_segments(clip_id)
        if loaded:
            segments = loaded
            break

    if not segments:
        return None

    # Treat all-placeholder metadata as "no information" → fallback.
    meaningful = [
        s
        for s in segments
        if (s.description and s.description != "Unknown") or s.objects
    ]
    if not meaningful:
        return None

    best_index = 0
    best_score = -1.0
    for i, segment in enumerate(segments):
        score = _score_segment(segment, scene_tokens)
        if score > best_score:
            best_score = score
            best_index = i

    best = segments[best_index]

    # If nothing matched at all, still center on the highest-confidence segment.
    reason_prefix = ""
    if best_score <= 0.0:
        best_index = max(
            range(len(segments)),
            key=lambda i: segments[i].confidence,
        )
        best = segments[best_index]
        reason_prefix = "no query/object match; highest-confidence segment; "

    trim_start, trim_end, window_reason = _compute_trim_window(
        best, clip_duration, narration_duration
    )

    return TrimSelection(
        segment=best,
        segment_index=best_index,
        segment_count=len(segments),
        trim_start=trim_start,
        trim_end=trim_end,
        score=max(0.0, best_score),
        reason=reason_prefix + window_reason,
    )
