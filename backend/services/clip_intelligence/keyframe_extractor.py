"""Extract keyframes from video clips (stub for Florence-2 phase)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Keyframe:
    """A single extracted frame reference."""

    timestamp: float
    path: Path | None = None


class KeyframeExtractor:
    """
    Extract representative frames from a clip.

    Phase 3.5: stub only — returns no keyframes. Florence-2 phase will
    implement FFmpeg-based extraction here.
    """

    def extract(self, video_path: Path, duration: float) -> list[Keyframe]:
        if not video_path.is_file():
            logger.debug("Keyframe extraction skipped; file missing: %s", video_path)
            return []
        logger.debug(
            "Keyframe extraction stub for %s (%.1fs) — no frames extracted yet",
            video_path.name,
            duration,
        )
        return []
