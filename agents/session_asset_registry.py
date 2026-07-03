"""Global clip registry for a single video generation session."""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

SESSION_REGISTRY_PATH = Path("assets/session_asset_registry.json")


def video_hash(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class RegistryEntry:
    clip_id: str
    source: str
    download_url: str
    scene_number: int
    video_hash: str


class SessionAssetRegistry:
    """Track clips selected during one Short to prevent cross-scene reuse."""

    def __init__(self, path: Path | str = SESSION_REGISTRY_PATH) -> None:
        self.path = Path(path)
        self._entries: list[RegistryEntry] = []
        self._clip_ids: set[str] = set()
        self._urls: set[str] = set()
        self._hashes: set[str] = set()

    def reset_for_session(self) -> None:
        """Clear registry at the start of a new video generation run."""
        self._entries.clear()
        self._clip_ids.clear()
        self._urls.clear()
        self._hashes.clear()
        self._persist()
        logger.info("Session asset registry reset for new video generation")

    def is_used(
        self,
        clip_id: str,
        download_url: str,
        url_hash: str | None = None,
    ) -> bool:
        digest = url_hash or video_hash(download_url)
        if clip_id and clip_id in self._clip_ids:
            return True
        if download_url in self._urls:
            return True
        if digest in self._hashes:
            return True
        return False

    def register(
        self,
        clip_id: str,
        source: str,
        download_url: str,
        scene_number: int,
    ) -> None:
        digest = video_hash(download_url)
        entry = RegistryEntry(
            clip_id=clip_id,
            source=source,
            download_url=download_url,
            scene_number=scene_number,
            video_hash=digest,
        )
        self._entries.append(entry)
        if clip_id:
            self._clip_ids.add(clip_id)
        self._urls.add(download_url)
        self._hashes.add(digest)
        self._persist()
        logger.info(
            "Registry: scene %d registered clip %s (%s)",
            scene_number,
            clip_id or digest,
            source,
        )

    def _persist(self) -> None:
        payload: dict[str, Any] = {
            "session_started_at": datetime.now(timezone.utc).isoformat(),
            "assets": [
                {
                    "clip_id": entry.clip_id,
                    "source": entry.source,
                    "download_url": entry.download_url,
                    "scene_number": entry.scene_number,
                    "video_hash": entry.video_hash,
                }
                for entry in self._entries
            ],
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def load(self) -> None:
        if not self.path.is_file():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        assets = data.get("assets")
        if not isinstance(assets, list):
            return
        for item in assets:
            if not isinstance(item, dict):
                continue
            self.register(
                str(item.get("clip_id") or ""),
                str(item.get("source") or "unknown"),
                str(item.get("download_url") or ""),
                int(item.get("scene_number") or 0),
            )
