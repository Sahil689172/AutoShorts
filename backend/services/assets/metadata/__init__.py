"""Asset metadata package."""

from backend.services.assets.metadata.models import AssetMetadata
from backend.services.assets.metadata.writer import MetadataWriter

__all__ = ["AssetMetadata", "MetadataWriter"]
