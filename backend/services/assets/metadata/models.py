"""Asset metadata models."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class AssetMetadata:
    asset_id: str
    provider: str
    download_url: str
    search_query: str
    topic: str
    subtopic: str
    tags: list[str] = field(default_factory=list)
    width: int = 0
    height: int = 0
    duration: float = 0.0
    download_date: str = ""
    local_path: str = ""
    media_type: str = "video"
    provider_clip_id: str = ""
    photographer: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AssetMetadata:
        return cls(
            asset_id=str(data.get("asset_id") or ""),
            provider=str(data.get("provider") or ""),
            download_url=str(data.get("download_url") or ""),
            search_query=str(data.get("search_query") or ""),
            topic=str(data.get("topic") or ""),
            subtopic=str(data.get("subtopic") or ""),
            tags=list(data.get("tags") or []),
            width=int(data.get("width") or 0),
            height=int(data.get("height") or 0),
            duration=float(data.get("duration") or 0.0),
            download_date=str(data.get("download_date") or ""),
            local_path=str(data.get("local_path") or ""),
            media_type=str(data.get("media_type") or "video"),
            provider_clip_id=str(data.get("provider_clip_id") or ""),
            photographer=str(data.get("photographer") or ""),
        )

    @staticmethod
    def now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()
