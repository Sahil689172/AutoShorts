"""Analyze clips and produce timeline metadata (placeholder until Florence-2)."""

from __future__ import annotations

import logging
from pathlib import Path

from backend.services.clip_intelligence.keyframe_extractor import KeyframeExtractor
from backend.services.clip_intelligence.metadata_store import MetadataStore
from backend.services.clip_intelligence.models import ClipAnalysis
from backend.services.clip_intelligence.timeline_builder import TimelineBuilder

logger = logging.getLogger(__name__)


class ClipAnalyzer:
    """
    Interface for clip understanding and timeline metadata.

    Phase 3.5: produces placeholder segments. Future phases will run
    Florence-2 (or similar) over keyframes to populate descriptions/objects.
    """

    def __init__(
        self,
        metadata_store: MetadataStore | None = None,
        timeline_builder: TimelineBuilder | None = None,
        keyframe_extractor: KeyframeExtractor | None = None,
    ) -> None:
        self.metadata_store = metadata_store or MetadataStore()
        self.timeline_builder = timeline_builder or TimelineBuilder()
        self.keyframe_extractor = keyframe_extractor or KeyframeExtractor()

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
        """Build placeholder timeline metadata for a downloaded clip."""
        path = Path(local_path)
        orientation = "portrait" if height >= width else "landscape"
        resolution = f"{width}x{height}" if width and height else "unknown"

        # Reserved for Florence-2: keyframes will drive per-segment analysis.
        self.keyframe_extractor.extract(path, duration)

        segments = self.timeline_builder.build_placeholder(duration)

        analysis = ClipAnalysis(
            clip_id=clip_id,
            provider=provider,
            duration=duration,
            resolution=resolution,
            orientation=orientation,
            timeline_segments=segments,
            local_path=str(path).replace("\\", "/"),
            analyzed_at=ClipAnalysis.now_iso(),
            ai_engine="placeholder",
        )
        logger.info(
            "ClipAnalyzer placeholder for %s (%s, %s, %.1fs)",
            clip_id,
            resolution,
            orientation,
            duration,
        )
        return analysis

    def save(self, analysis: ClipAnalysis) -> Path:
        """Persist timeline metadata to assets/library/metadata/."""
        return self.metadata_store.save(analysis)

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
