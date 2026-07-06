"""Persist per-asset metadata JSON files."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from backend.services.assets.metadata.models import AssetMetadata
from backend.services.assets.utils.paths import INDEX_DIR

logger = logging.getLogger(__name__)


class MetadataWriter:
    """Write assets/library/index/{asset_id}.json records."""

    def __init__(self, index_dir: Path = INDEX_DIR) -> None:
        self.index_dir = index_dir

    def write(self, metadata: AssetMetadata) -> Path:
        self.index_dir.mkdir(parents=True, exist_ok=True)
        path = self.index_dir / f"{metadata.asset_id}.json"
        path.write_text(
            json.dumps(metadata.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        logger.debug("Wrote metadata %s", path)
        return path

    def read(self, asset_id: str) -> AssetMetadata | None:
        path = self.index_dir / f"{asset_id}.json"
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return AssetMetadata.from_dict(data)
        except (OSError, json.JSONDecodeError, TypeError):
            return None
