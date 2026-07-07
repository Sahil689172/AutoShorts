"""Analyze clips and produce timeline metadata (Florence-2 + shot detection)."""

from __future__ import annotations

import logging
import time
from pathlib import Path

from backend.services.clip_intelligence.florence_provider import FlorenceProvider
from backend.services.clip_intelligence.keyframe_extractor import KeyframeExtractor
from backend.services.clip_intelligence.metadata_store import MetadataStore
from backend.services.clip_intelligence.models import ClipAnalysis, TimelineSegment
from backend.services.clip_intelligence.timeline_builder import TimelineBuilder

logger = logging.getLogger(__name__)


class ClipAnalyzer:
    """
    Interface for clip understanding and timeline metadata.

    Phase 3.6:
    - Detect shots with PySceneDetect.
    - Extract one keyframe per shot.
    - Run Florence-2 on each keyframe.
    - Save segments to assets/library/metadata/{clip_id}.timeline.json

    Never fails collection: any errors fall back to placeholder metadata.
    """

    def __init__(
        self,
        metadata_store: MetadataStore | None = None,
        timeline_builder: TimelineBuilder | None = None,
        keyframe_extractor: KeyframeExtractor | None = None,
        florence: FlorenceProvider | None = None,
    ) -> None:
        self.metadata_store = metadata_store or MetadataStore()
        self.timeline_builder = timeline_builder or TimelineBuilder()
        self.keyframe_extractor = keyframe_extractor or KeyframeExtractor()
        self.florence = florence or FlorenceProvider()

    def analyze(
        self,
        *,
        clip_id: str,
        provider: str,
        local_path: str | Path,
        width: int,
        height: int,
        duration: float,
    ) -> ClipAnalysis:
        """Analyze a downloaded clip into timeline segments (Florence-2)."""
        started = time.perf_counter()
        path = Path(local_path)
        orientation = "portrait" if height >= width else "landscape"
        resolution = f"{width}x{height}" if width and height else "unknown"

        segments: list[TimelineSegment] = []
        ai_engine = "florence-2"
        shot_count = 0
        try:
            keyframes = self.keyframe_extractor.extract(path, duration)
            shot_count = len(keyframes)
            for kf in keyframes:
                result = self.florence.analyze(kf.image)
                segments.append(
                    TimelineSegment(
                        start=max(0.0, float(kf.timestamp - 0.0001)),  # overwritten below
                        end=max(0.0, float(kf.timestamp + 0.0001)),
                        description=result.description or "Unknown",
                        objects=list(result.objects or []),
                        confidence=float(result.confidence or 0.0),
                    )
                )
        except Exception as exc:
            # Florence or shot detection failed; keep placeholder and never fail collection.
            logger.warning("Florence analysis failed for %s: %s", clip_id, exc)
            segments = []
            ai_engine = "placeholder"

        # If Florence failed or produced nothing, fall back to placeholder.
        if not segments:
            segments = self.timeline_builder.build_placeholder(duration)

        # Convert shot-centered segments into continuous timeline segments.
        # We intentionally do not sample every frame; one representative frame per shot.
        if segments and segments != self.timeline_builder.build_placeholder(duration):
            # Re-detect scenes (without decoding images again) by reading keyframes list length:
            # If keyframe extractor returned timestamps, approximate boundaries by midpoints.
            times = sorted({max(0.0, float(s.start + s.end) / 2.0) for s in segments})
            if times:
                bounds = [0.0] + [(times[i] + times[i + 1]) / 2.0 for i in range(len(times) - 1)] + [max(0.0, float(duration))]
                rebuilt: list[TimelineSegment] = []
                for i, s in enumerate(segments[: len(bounds) - 1]):
                    rebuilt.append(
                        TimelineSegment(
                            start=float(bounds[i]),
                            end=float(bounds[i + 1]),
                            description=s.description,
                            objects=s.objects,
                            confidence=s.confidence,
                        )
                    )
                segments = rebuilt or segments

        analysis = ClipAnalysis(
            clip_id=clip_id,
            provider=provider,
            duration=duration,
            resolution=resolution,
            orientation=orientation,
            timeline_segments=segments,
            local_path=str(path).replace("\\", "/"),
            analyzed_at=ClipAnalysis.now_iso(),
            ai_engine=ai_engine,
        )

        elapsed = time.perf_counter() - started
        logger.info("Clip: %s | Shot Count: %d | Analysis Time: %.2fs", clip_id, shot_count, elapsed)
        return analysis

    def save(self, analysis: ClipAnalysis) -> Path:
        """Persist timeline metadata to assets/library/metadata/ (Phase 3.6 list format)."""
        path = self.metadata_store.save(analysis)
        logger.info("Timeline Saved: %s", str(path).replace("\\", "/"))
        return path

    def load(self, clip_id: str) -> ClipAnalysis | None:
        """Load timeline metadata if it exists."""
        return self.metadata_store.load(clip_id)

    def exists(self, clip_id: str) -> bool:
        """Return True when timeline metadata file is present."""
        return self.metadata_store.exists(clip_id)

    def analyze_and_save(
        self,
        *,
        clip_id: str,
        provider: str,
        local_path: str | Path,
        width: int,
        height: int,
        duration: float,
    ) -> ClipAnalysis:
        """Convenience: analyze then save."""
        analysis = self.analyze(
            clip_id=clip_id,
            provider=provider,
            local_path=local_path,
            width=width,
            height=height,
            duration=duration,
        )
        self.save(analysis)
        return analysis
