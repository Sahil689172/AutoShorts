"""On-disk asset library storage."""

from __future__ import annotations

import logging
from pathlib import Path

import requests

from backend.services.assets.metadata.models import AssetMetadata
from backend.services.assets.metadata.writer import MetadataWriter
from backend.services.assets.utils.paths import LIBRARY_ROOT, library_media_path
from backend.services.clip_intelligence.clip_analyzer import ClipAnalyzer

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 30
MIN_VIDEO_BYTES = 100_000


class LibraryStorage:
    """Download and store media under assets/library/{topic}/{subtopic}/."""

    def __init__(
        self,
        library_root: Path = LIBRARY_ROOT,
        metadata_writer: MetadataWriter | None = None,
        clip_analyzer: ClipAnalyzer | None = None,
    ) -> None:
        self.library_root = library_root
        self.metadata_writer = metadata_writer or MetadataWriter()
        self.clip_analyzer = clip_analyzer or ClipAnalyzer()

    def download_asset(
        self,
        url: str,
        dest: Path,
        session: requests.Session | None = None,
    ) -> None:
        http = session or requests.Session()
        http.headers.setdefault("User-Agent", "AutoShorts-Collector/1.0")
        response = http.get(url, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        content = response.content
        if len(content) < MIN_VIDEO_BYTES:
            raise ValueError(f"Downloaded file too small ({len(content)} bytes)")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(content)

    def store(
        self,
        metadata: AssetMetadata,
        url: str,
        extension: str = ".mp4",
        session: requests.Session | None = None,
    ) -> Path:
        dest = library_media_path(
            metadata.topic,
            metadata.subtopic,
            metadata.asset_id,
            extension,
        )
        self.download_asset(url, dest, session=session)
        metadata.local_path = str(dest).replace("\\", "/")
        if not metadata.download_date:
            metadata.download_date = AssetMetadata.now_iso()
        self.metadata_writer.write(metadata)
        self._write_timeline_metadata(metadata, dest)
        logger.info("Stored asset %s -> %s", metadata.asset_id, dest)
        return dest

    def _write_timeline_metadata(self, metadata: AssetMetadata, dest: Path) -> None:
        """Create placeholder timeline metadata for every collected clip."""
        try:
            self.clip_analyzer.analyze_and_save(
                clip_id=metadata.asset_id,
                provider=metadata.provider,
                local_path=dest,
                width=metadata.width,
                height=metadata.height,
                duration=metadata.duration,
            )
        except Exception as exc:
            logger.warning(
                "Timeline metadata failed for %s: %s",
                metadata.asset_id,
                exc,
            )
