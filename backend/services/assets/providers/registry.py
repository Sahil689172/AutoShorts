"""Provider registry for the offline collection engine."""

from __future__ import annotations

from backend.services.assets.providers.asset_provider import AssetProvider
from backend.services.assets.providers.pexels_provider import PexelsProvider

PROVIDER_REGISTRY: dict[str, type[AssetProvider]] = {
    "pexels": PexelsProvider,
}


def resolve_providers(names: list[str]) -> list[AssetProvider]:
    """Instantiate providers by name; skip unknown or unconfigured."""
    providers: list[AssetProvider] = []
    for name in names:
        key = name.strip().lower()
        cls = PROVIDER_REGISTRY.get(key)
        if cls is None:
            continue
        instance = cls()
        if instance.is_configured():
            providers.append(instance)
    return providers


def available_provider_names() -> list[str]:
    return sorted(PROVIDER_REGISTRY.keys())
