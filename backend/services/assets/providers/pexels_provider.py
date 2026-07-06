"""Pexels video provider — generation pipeline parity with legacy PexelsVideoClient."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import requests

from agents.visual_asset_agent import APIKeyMissingError, REQUEST_TIMEOUT, SearchCache
from backend.services.assets.providers.asset_provider import (
    AssetProvider,
    AssetProviderMetadata,
    ProviderAsset,
)

logger = logging.getLogger(__name__)

PEXELS_VIDEOS_SEARCH_URL = "https://api.pexels.com/v1/videos/search"
MIN_VIDEO_WIDTH = 720
MIN_VIDEO_HEIGHT = 1080
MIN_VIDEO_DURATION = 3


class PexelsProvider(AssetProvider):
    """Search portrait stock videos on Pexels."""

    name = "pexels"

    def __init__(
        self,
        api_key: str | None = None,
        cache: SearchCache | None = None,
    ) -> None:
        self.api_key = (api_key or os.environ.get("PEXELS_API_KEY", "")).strip()
        self.cache = cache or SearchCache()
        self.session = requests.Session()
        if self.api_key:
            self.session.headers["Authorization"] = self.api_key

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def _require_key(self) -> None:
        if not self.api_key:
            raise APIKeyMissingError(
                "PEXELS_API_KEY is not set. Add it to your .env file."
            )

    def search(self, query: str, *, per_page: int = 6) -> list[ProviderAsset]:
        self._require_key()
        cached = self.cache.get("pexels_video", query)
        if cached is not None:
            logger.info("Pexels video cache hit for query: %s", query)
            assets = [self._from_cache(item) for item in cached if item]
            assets.sort(key=lambda a: a.score(), reverse=True)
            return assets

        params = {
            "query": query,
            "per_page": per_page,
            "orientation": "portrait",
        }
        try:
            response = self.session.get(
                PEXELS_VIDEOS_SEARCH_URL,
                params=params,
                timeout=REQUEST_TIMEOUT,
            )
            response.raise_for_status()
            data = response.json()
        except requests.RequestException as exc:
            logger.error("Pexels video search failed for '%s': %s", query, exc)
            return []

        videos = data.get("videos") or []
        candidates: list[ProviderAsset] = []
        cache_payload: list[dict[str, Any]] = []

        for video in videos:
            if not isinstance(video, dict):
                continue
            duration = float(video.get("duration") or 0)
            if duration < MIN_VIDEO_DURATION:
                continue
            resolved = self._best_video_file(video.get("video_files") or [])
            if resolved is None:
                continue
            url, width, height = resolved[0], resolved[1], resolved[2]
            if width < MIN_VIDEO_WIDTH or height < MIN_VIDEO_HEIGHT:
                continue
            user = video.get("user") or {}
            clip_id = str(video.get("id") or "")
            candidate = ProviderAsset(
                download_url=url,
                width=width,
                height=height,
                duration=duration,
                clip_id=clip_id,
                source="pexels_video",
                provider=self.name,
                media_type="video",
                photographer=str(user.get("name") or ""),
                tags=tuple(t.strip() for t in query.split() if t.strip()),
            )
            candidates.append(candidate)
            cache_payload.append(
                {
                    "url": url,
                    "width": width,
                    "height": height,
                    "duration": duration,
                    "clip_id": clip_id,
                    "source": "pexels_video",
                    "media_type": "video",
                    "photographer": candidate.photographer,
                }
            )

        self.cache.set("pexels_video", query, cache_payload)
        candidates.sort(key=lambda c: c.score(), reverse=True)
        logger.info("Pexels videos returned %d matches for: %s", len(candidates), query)
        return candidates

    def download(
        self,
        asset: ProviderAsset,
        dest: Path,
        session: requests.Session | None = None,
    ) -> Path:
        http = session or self.session
        return self._default_download(asset, dest, session=http)

    def get_metadata(self, asset: ProviderAsset) -> AssetProviderMetadata:
        return AssetProviderMetadata(
            asset_id=asset.asset_id,
            provider=self.name,
            clip_id=asset.clip_id,
            download_url=asset.download_url,
            width=asset.width,
            height=asset.height,
            duration=asset.duration,
            media_type=asset.media_type,
            source=asset.source,
            photographer=asset.photographer,
        )

    @staticmethod
    def _best_video_file(files: list[Any]) -> tuple[str, int, int] | None:
        mp4_files: list[tuple[str, int, int, int]] = []
        for item in files:
            if not isinstance(item, dict):
                continue
            if str(item.get("file_type") or "").lower() != "video/mp4":
                continue
            link = str(item.get("link") or "").strip()
            width = int(item.get("width") or 0)
            height = int(item.get("height") or 0)
            if not link or width <= 0 or height <= 0:
                continue
            mp4_files.append((link, width, height, width * height))

        if not mp4_files:
            return None
        mp4_files.sort(key=lambda row: (row[3], row[2]), reverse=True)
        link, width, height, _ = mp4_files[0]
        return link, width, height

    @staticmethod
    def _from_cache(item: dict[str, Any]) -> ProviderAsset:
        return ProviderAsset(
            download_url=str(item["url"]),
            width=int(item["width"]),
            height=int(item["height"]),
            duration=float(item.get("duration") or MIN_VIDEO_DURATION),
            clip_id=str(item.get("clip_id") or ""),
            source="pexels_video",
            provider="pexels",
            media_type=str(item.get("media_type") or "video"),
            photographer=str(item.get("photographer") or ""),
            tags=tuple(),
        )
