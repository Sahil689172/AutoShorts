"""Deduplication store for asset collection."""

from __future__ import annotations

import hashlib
import logging

logger = logging.getLogger(__name__)


class DedupStore:
    """Track provider clip IDs and download URLs to prevent duplicate ingestion."""

    def __init__(self) -> None:
        self._asset_ids: set[str] = set()
        self._clip_keys: set[str] = set()
        self._urls: set[str] = set()

    @staticmethod
    def clip_key(provider: str, clip_id: str) -> str:
        return f"{provider}:{clip_id}"

    def load_from_records(
        self,
        asset_ids: set[str],
        clip_keys: set[str],
        urls: set[str],
    ) -> None:
        self._asset_ids = set(asset_ids)
        self._clip_keys = set(clip_keys)
        self._urls = set(urls)

    def is_duplicate(
        self,
        asset_id: str,
        provider: str,
        clip_id: str,
        download_url: str,
    ) -> bool:
        if asset_id in self._asset_ids:
            return True
        if download_url in self._urls:
            return True
        if clip_id:
            key = self.clip_key(provider, clip_id)
            if key in self._clip_keys:
                return True
        url_hash = hashlib.sha256(download_url.encode()).hexdigest()
        if url_hash in self._urls:
            return True
        return False

    def register(
        self,
        asset_id: str,
        provider: str,
        clip_id: str,
        download_url: str,
    ) -> None:
        self._asset_ids.add(asset_id)
        self._urls.add(download_url)
        self._urls.add(hashlib.sha256(download_url.encode()).hexdigest())
        if clip_id:
            self._clip_keys.add(self.clip_key(provider, clip_id))
