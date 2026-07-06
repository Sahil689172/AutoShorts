"""Persist clip timeline metadata on disk."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from backend.services.assets.utils.paths import TIMELINE_METADATA_DIR
from backend.services.clip_intelligence.models import ClipAnalysis

logger = logging.getLogger(__name__)


def timeline_metadata_path(clip_id: str, base_dir: Path = TIMELINE_METADATA_DIR) -> Path:
    safe_id = re.sub(r"[^\w.-]", "_", clip_id.strip())
    return base_dir / f"{safe_id}.timeline.json"


class MetadataStore:
    """Read and write {clip_id}.timeline.json files."""

    def __init__(self, base_dir: Path = TIMELINE_METADATA_DIR) -> None:
        self.base_dir = base_dir

    def save(self, analysis: ClipAnalysis) -> Path:
        path = timeline_metadata_path(analysis.clip_id, self.base_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(analysis.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        logger.debug("Saved timeline metadata %s", path)
        return path

    def load(self, clip_id: str) -> ClipAnalysis | None:
        path = timeline_metadata_path(clip_id, self.base_dir)
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return ClipAnalysis.from_dict(data)
        except (OSError, json.JSONDecodeError, TypeError) as exc:
            logger.warning("Cannot load timeline metadata %s: %s", path, exc)
            return None

    def exists(self, clip_id: str) -> bool:
        return timeline_metadata_path(clip_id, self.base_dir).is_file()

    def path_for(self, clip_id: str) -> Path:
        return timeline_metadata_path(clip_id, self.base_dir)
