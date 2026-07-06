"""Data models for clip timeline intelligence."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class TimelineSegment:
    """A time-bounded description of clip content."""

    start_time: float
    end_time: float
    description: str = "Unknown"
    objects: list[str] = field(default_factory=list)
    confidence: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TimelineSegment:
        return cls(
            start_time=float(data.get("start_time") or 0),
            end_time=float(data.get("end_time") or 0),
            description=str(data.get("description") or "Unknown"),
            objects=list(data.get("objects") or []),
            confidence=float(data.get("confidence") or 0),
        )


@dataclass
class ClipAnalysis:
    """Timeline metadata for a single video clip."""

    clip_id: str
    provider: str
    duration: float
    resolution: str
    orientation: str
    timeline_segments: list[TimelineSegment] = field(default_factory=list)
    local_path: str = ""
    analyzed_at: str = ""
    ai_engine: str = "placeholder"

    def to_dict(self) -> dict[str, Any]:
        return {
            "clip_id": self.clip_id,
            "provider": self.provider,
            "duration": self.duration,
            "resolution": self.resolution,
            "orientation": self.orientation,
            "timeline_segments": [s.to_dict() for s in self.timeline_segments],
            "local_path": self.local_path,
            "analyzed_at": self.analyzed_at,
            "ai_engine": self.ai_engine,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ClipAnalysis:
        segments_raw = data.get("timeline_segments") or []
        segments = [
            TimelineSegment.from_dict(s) for s in segments_raw if isinstance(s, dict)
        ]
        return cls(
            clip_id=str(data.get("clip_id") or ""),
            provider=str(data.get("provider") or ""),
            duration=float(data.get("duration") or 0),
            resolution=str(data.get("resolution") or ""),
            orientation=str(data.get("orientation") or ""),
            timeline_segments=segments,
            local_path=str(data.get("local_path") or ""),
            analyzed_at=str(data.get("analyzed_at") or ""),
            ai_engine=str(data.get("ai_engine") or "placeholder"),
        )

    @staticmethod
    def now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()
