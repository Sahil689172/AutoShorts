"""Orchestrate multi-provider asset search for the generation pipeline."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from backend.services.assets.providers.asset_provider import ProviderAsset
from backend.services.assets.providers.pexels_provider import PexelsProvider

if TYPE_CHECKING:
    from agents.visual_asset_agent import SearchCache

logger = logging.getLogger(__name__)

# Future providers — register here when implemented (disabled by default).
# from backend.services.assets.providers.local_library_provider import LocalLibraryProvider
# from backend.services.assets.providers.pixabay_video_provider import PixabayVideoProvider
# from backend.services.assets.providers.archive_provider import ArchiveProvider

DEFAULT_ENABLED_PROVIDERS = ("pexels",)


class AssetProviderManager:
    """
    Unified entry point for video asset search during generation.

    Currently enables Pexels only; additional providers plug in without
    changing VisualTimelineAgent.
    """

    def __init__(
        self,
        search_cache: SearchCache | None = None,
        enabled_providers: tuple[str, ...] | None = None,
    ) -> None:
        self._enabled_names = enabled_providers or DEFAULT_ENABLED_PROVIDERS
        self._providers = self._build_providers(search_cache)

    def _build_providers(self, search_cache: SearchCache | None) -> list:
        instances = []
        for name in self._enabled_names:
            key = name.strip().lower()
            if key == "pexels":
                instances.append(PexelsProvider(cache=search_cache))
            # elif key == "local_library":
            #     instances.append(LocalLibraryProvider())
            # elif key == "pixabay":
            #     instances.append(PixabayVideoProvider(cache=search_cache))
            else:
                logger.debug("Provider %r is not registered or is disabled", name)
        return [p for p in instances if p.is_configured()]

    def is_configured(self) -> bool:
        """True when at least one enabled provider is ready."""
        return bool(self._providers)

    def search(self, query: str, *, per_page: int = 6) -> list[ProviderAsset]:
        """Search all enabled providers and return a merged, ranked candidate list."""
        merged: list[ProviderAsset] = []
        seen_ids: set[str] = set()
        seen_urls: set[str] = set()

        for provider in self._providers:
            try:
                results = provider.search(query, per_page=per_page)
            except Exception as exc:
                logger.warning(
                    "%s search failed for %r: %s",
                    provider.name,
                    query,
                    exc,
                )
                continue
            for asset in results:
                if asset.clip_id and asset.clip_id in seen_ids:
                    continue
                if asset.download_url in seen_urls:
                    continue
                if asset.clip_id:
                    seen_ids.add(asset.clip_id)
                seen_urls.add(asset.download_url)
                merged.append(asset)

        merged.sort(key=lambda a: a.score(), reverse=True)
        logger.info(
            "Provider manager returned %d merged candidates for %r",
            len(merged),
            query,
        )
        return merged

    @property
    def provider_names(self) -> list[str]:
        return [p.name for p in self._providers]
