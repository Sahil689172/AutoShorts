"""Master index for the local asset library."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.services.assets.metadata.models import AssetMetadata
from backend.services.assets.utils.paths import MASTER_INDEX_PATH

logger = logging.getLogger(__name__)


class MasterIndex:
    """Maintain assets/library/index/master_index.json."""

    def __init__(self, path: Path = MASTER_INDEX_PATH) -> None:
        self.path = path
        self._data: dict[str, Any] = self._empty()

    @staticmethod
    def _empty() -> dict[str, Any]:
        return {
            "version": 1,
            "updated_at": None,
            "total_assets": 0,
            "asset_ids": [],
            "by_provider": {},
            "by_topic": {},
            "entries": {},
        }

    def load(self) -> None:
        if not self.path.is_file():
            self._data = self._empty()
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            self._data = raw if isinstance(raw, dict) else self._empty()
        except (OSError, json.JSONDecodeError):
            logger.warning("Corrupt master index; starting fresh")
            self._data = self._empty()

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._data["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._data["total_assets"] = len(self._data.get("asset_ids") or [])
        self.path.write_text(
            json.dumps(self._data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    @property
    def asset_ids(self) -> set[str]:
        return set(self._data.get("asset_ids") or [])

    def clip_keys_and_urls(self) -> tuple[set[str], set[str]]:
        clip_keys: set[str] = set()
        urls: set[str] = set()
        entries = self._data.get("entries")
        if not isinstance(entries, dict):
            return clip_keys, urls
        for entry in entries.values():
            if not isinstance(entry, dict):
                continue
            provider = str(entry.get("provider") or "")
            clip_id = str(entry.get("provider_clip_id") or "")
            url = str(entry.get("download_url") or "")
            if provider and clip_id:
                clip_keys.add(f"{provider}:{clip_id}")
            if url:
                urls.add(url)
        return clip_keys, urls

    def add(self, metadata: AssetMetadata) -> None:
        asset_ids: list[str] = list(self._data.setdefault("asset_ids", []))
        if metadata.asset_id not in asset_ids:
            asset_ids.append(metadata.asset_id)
        self._data["asset_ids"] = asset_ids

        by_provider: dict[str, int] = self._data.setdefault("by_provider", {})
        by_provider[metadata.provider] = by_provider.get(metadata.provider, 0) + 1

        by_topic: dict[str, int] = self._data.setdefault("by_topic", {})
        by_topic[metadata.topic] = by_topic.get(metadata.topic, 0) + 1

        entries: dict[str, Any] = self._data.setdefault("entries", {})
        entries[metadata.asset_id] = {
            "provider": metadata.provider,
            "provider_clip_id": metadata.provider_clip_id,
            "download_url": metadata.download_url,
            "topic": metadata.topic,
            "subtopic": metadata.subtopic,
            "local_path": metadata.local_path,
            "search_query": metadata.search_query,
        }
