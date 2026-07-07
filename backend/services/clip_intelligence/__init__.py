"""Clip intelligence infrastructure for future AI-powered understanding."""

from backend.services.clip_intelligence.clip_analyzer import ClipAnalyzer
from backend.services.assets.utils.paths import TIMELINE_METADATA_DIR
from backend.services.clip_intelligence.config import (
    DEFAULT_VISION_MODEL,
    VISION_MODEL,
    get_vision_model,
)
from backend.services.clip_intelligence.metadata_store import (
    MetadataStore,
    timeline_metadata_path,
)
from backend.services.clip_intelligence.models import ClipAnalysis, TimelineSegment

__all__ = [
    "ClipAnalysis",
    "ClipAnalyzer",
    "DEFAULT_VISION_MODEL",
    "MetadataStore",
    "TIMELINE_METADATA_DIR",
    "TimelineSegment",
    "VISION_MODEL",
    "get_vision_model",
    "timeline_metadata_path",
]
