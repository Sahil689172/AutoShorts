"""Asset collection and library services (offline, separate from video generation)."""

from backend.services.assets.collector.asset_collector import AssetCollector, CollectionReport

__all__ = ["AssetCollector", "CollectionReport"]
