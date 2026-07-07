"""Persist clip timeline metadata on disk."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from backend.services.assets.utils.paths import TIMELINE_METADATA_DIR
from backend.services.clip_intelligence.models import ClipAnalysis, TimelineSegment

logger = logging.getLogger(__name__)


def timeline_metadata_path(clip_id: str, base_dir: Path = TIMELINE_METADATA_DIR) -> Path:
    safe_id = re.sub(r"[^\w.-]", "_", clip_id.strip())
    return base_dir / f"{safe_id}.timeline.json"


class MetadataStore:
    """Read and write {clip_id}.timeline.json files."""

    def __init__(self, base_dir: Path = TIMELINE_METADATA_DIR) -> None:
        self.base_dir = base_dir

    def save_segments(self, clip_id: str, segments: list[TimelineSegment]) -> Path:
        """
        Save timeline metadata in Phase 3.6 format:

        [
          {"start": 0.0, "end": 2.4, "description": "...", "objects": [...], "confidence": 0.95},
          ...
        ]
        """
        path = timeline_metadata_path(clip_id, self.base_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps([s.to_dict() for s in segments], indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        logger.debug("Saved timeline metadata %s", path)
        return path

    def save(self, analysis: ClipAnalysis) -> Path:
        """
        Backward-compatible convenience: save analysis.timeline_segments as Phase 3.6 list.
        """
        return self.save_segments(analysis.clip_id, analysis.timeline_segments)

    def load_segments(self, clip_id: str) -> list[TimelineSegment] | None:
        path = timeline_metadata_path(clip_id, self.base_dir)
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            # Phase 3.6: list[segment]
            if isinstance(data, list):
                return [
                    TimelineSegment.from_dict(item)
                    for item in data
                    if isinstance(item, dict)
                ]
            # Phase 3.5: ClipAnalysis dict
            if isinstance(data, dict):
                analysis = ClipAnalysis.from_dict(data)
                return analysis.timeline_segments
            return None
        except (OSError, json.JSONDecodeError, TypeError) as exc:
            logger.warning("Cannot load timeline metadata %s: %s", path, exc)
            return None

    def load(self, clip_id: str) -> ClipAnalysis | None:
        """
        Backward-compatible loader.

        - Phase 3.6 file: returns a ClipAnalysis with segments populated and other fields blank.
        - Phase 3.5 file: returns the original ClipAnalysis.
        """
        path = timeline_metadata_path(clip_id, self.base_dir)
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return ClipAnalysis.from_dict(data)
            if isinstance(data, list):
                segments = [
                    TimelineSegment.from_dict(item)
                    for item in data
                    if isinstance(item, dict)
                ]
                return ClipAnalysis(
                    clip_id=clip_id,
                    provider="",
                    duration=0.0,
                    resolution="",
                    orientation="",
                    timeline_segments=segments,
                    local_path="",
                    analyzed_at="",
                    ai_engine="",
                )
            return None
        except (OSError, json.JSONDecodeError, TypeError) as exc:
            logger.warning("Cannot load timeline metadata %s: %s", path, exc)
            return None

    def exists(self, clip_id: str) -> bool:
        return timeline_metadata_path(clip_id, self.base_dir).is_file()

    def path_for(self, clip_id: str) -> Path:
        return timeline_metadata_path(clip_id, self.base_dir)
