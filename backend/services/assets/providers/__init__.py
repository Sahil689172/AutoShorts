"""Remote asset providers."""

from backend.services.assets.providers.asset_provider import (
    AssetProvider,
    AssetProviderMetadata,
    ProviderAsset,
    RemoteAsset,
)
from backend.services.assets.providers.pexels_provider import PexelsProvider
from backend.services.assets.providers.registry import (
    available_provider_names,
    resolve_providers,
)

__all__ = [
    "AssetProvider",
    "AssetProviderMetadata",
    "PexelsProvider",
    "ProviderAsset",
    "RemoteAsset",
    "available_provider_names",
    "resolve_providers",
]
