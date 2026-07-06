"""Unified asset provider interface for generation and collection pipelines."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import requests

MIN_VIDEO_WIDTH = 720
MIN_VIDEO_HEIGHT = 1080
MIN_VIDEO_DURATION = 3
REQUEST_TIMEOUT = 30
MIN_VIDEO_BYTES = 100_000


@dataclass(frozen=True)
class AssetProviderMetadata:
    """Descriptive metadata for a provider asset."""

    asset_id: str
    provider: str
    clip_id: str
    download_url: str
    width: int
    height: int
    duration: float
    media_type: str = "video"
    source: str = "pexels_video"
    photographer: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProviderAsset:
    """Unified candidate returned by all asset providers."""

    download_url: str
    width: int
    height: int
    duration: float
    clip_id: str = ""
    source: str = "pexels_video"
    provider: str = "pexels"
    media_type: str = "video"
    photographer: str = ""
    source_query: str = ""
    tags: tuple[str, ...] = ()
    title: str = ""
    description: str = ""

    @property
    def url(self) -> str:
        return self.download_url

    @property
    def is_portrait(self) -> bool:
        return self.height >= self.width

    @property
    def orientation(self) -> str:
        return "portrait" if self.is_portrait else "landscape"

    @property
    def meets_minimum(self) -> bool:
        return (
            self.width >= MIN_VIDEO_WIDTH
            and self.height >= MIN_VIDEO_HEIGHT
            and self.duration >= MIN_VIDEO_DURATION
        )

    def score(self) -> float:
        score = float(self.width * self.height)
        if self.is_portrait:
            score *= 1.3
        if self.height >= 1920 and self.width >= 1080:
            score *= 1.15
        if self.duration >= 8:
            score *= 1.05
        return score

    @property
    def asset_id(self) -> str:
        if self.clip_id:
            return f"{self.provider}_{self.clip_id}"
        return f"{self.provider}_asset"


class AssetProvider(ABC):
    """Abstract stock asset provider."""

    name: str

    @abstractmethod
    def is_configured(self) -> bool:
        """Return True when the provider can serve requests."""

    @abstractmethod
    def search(self, query: str, *, per_page: int = 6) -> list[ProviderAsset]:
        """Search for assets matching query."""

    @abstractmethod
    def download(
        self,
        asset: ProviderAsset,
        dest: Path,
        session: requests.Session | None = None,
    ) -> Path:
        """Download asset bytes to dest."""

    @abstractmethod
    def get_metadata(self, asset: ProviderAsset) -> AssetProviderMetadata:
        """Return metadata for an asset."""

    def _default_download(
        self,
        asset: ProviderAsset,
        dest: Path,
        session: requests.Session | None = None,
    ) -> Path:
        http = session or requests.Session()
        http.headers.setdefault("User-Agent", "AutoShorts-AssetProvider/1.0")
        response = http.get(asset.download_url, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        content = response.content
        if len(content) < MIN_VIDEO_BYTES:
            raise ValueError(f"Downloaded file too small ({len(content)} bytes)")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(content)
        return dest


# Backward-compatible alias used by the collection engine (Phase 3.1).
RemoteAsset = ProviderAsset
