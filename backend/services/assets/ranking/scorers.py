"""Modular scoring functions for clip ranking (0.0–1.0 each)."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from backend.services.assets.providers.asset_provider import (
    MIN_VIDEO_DURATION,
    ProviderAsset,
)
from backend.services.assets.ranking.models import SceneRankContext

if TYPE_CHECKING:
    from agents.session_asset_registry import SessionAssetRegistry

TARGET_WIDTH = 1080
TARGET_HEIGHT = 1920
TARGET_PIXELS = TARGET_WIDTH * TARGET_HEIGHT
IDEAL_ASPECT = TARGET_WIDTH / TARGET_HEIGHT
IDEAL_DURATION_MIN = 5.0
IDEAL_DURATION_MAX = 15.0


def tokenize(text: str) -> set[str]:
    words = re.findall(r"\w+", text.lower())
    return {w for w in words if len(w) > 2}


class SemanticScorer:
    """
    Metadata-based semantic relevance (no embeddings).

    Compares scene context to asset search query, tags, title, and description.
    Designed for future replacement with embedding similarity.
    """

    def score(self, candidate: ProviderAsset, context: SceneRankContext) -> float:
        scene_tokens = tokenize(f"{context.title} {context.visual_description}")
        for query in context.queries:
            scene_tokens |= tokenize(query)

        asset_text = " ".join(
            [
                candidate.source_query,
                " ".join(candidate.tags),
                candidate.title,
                candidate.description,
                candidate.photographer,
            ]
        )
        asset_tokens = tokenize(asset_text)

        if not scene_tokens and not asset_tokens:
            return 0.5
        if not asset_tokens:
            return 0.0

        intersection = scene_tokens & asset_tokens
        union = scene_tokens | asset_tokens
        jaccard = len(intersection) / len(union) if union else 0.0

        query_set = {q.strip().lower() for q in context.queries}
        if candidate.source_query.strip().lower() in query_set:
            jaccard = min(1.0, jaccard + 0.25)

        return min(1.0, max(0.0, jaccard))


class ResolutionScorer:
    """Normalize pixel count against 1080×1920 Shorts target."""

    def score(self, candidate: ProviderAsset, context: SceneRankContext) -> float:
        pixels = candidate.width * candidate.height
        if pixels <= 0:
            return 0.0
        return min(1.0, pixels / TARGET_PIXELS)


class PortraitScorer:
    """Prefer portrait orientation close to 9:16."""

    def score(self, candidate: ProviderAsset, context: SceneRankContext) -> float:
        if candidate.width <= 0 or candidate.height <= 0:
            return 0.0
        if candidate.height < candidate.width:
            return 0.25
        aspect = candidate.width / candidate.height
        deviation = abs(aspect - IDEAL_ASPECT) / IDEAL_ASPECT
        return min(1.0, max(0.0, 1.0 - deviation))


class DurationScorer:
    """Prefer clips long enough to trim (5–15s ideal)."""

    def score(self, candidate: ProviderAsset, context: SceneRankContext) -> float:
        duration = candidate.duration
        if duration < MIN_VIDEO_DURATION:
            return 0.0
        if IDEAL_DURATION_MIN <= duration <= IDEAL_DURATION_MAX:
            return 1.0
        if duration < IDEAL_DURATION_MIN:
            return max(0.0, (duration - MIN_VIDEO_DURATION) / (IDEAL_DURATION_MIN - MIN_VIDEO_DURATION))
        # Longer clips still usable
        return max(0.4, 1.0 - (duration - IDEAL_DURATION_MAX) / 30.0)


class DiversityScorer:
    """Penalize clips already used in the current video session."""

    def __init__(self, registry: SessionAssetRegistry) -> None:
        self.registry = registry

    def score(self, candidate: ProviderAsset, context: SceneRankContext) -> float:
        from agents.session_asset_registry import video_hash

        clip_id = candidate.clip_id or ""
        url_hash = video_hash(candidate.download_url)
        if self.registry.is_used(clip_id, candidate.download_url, url_hash):
            return 0.0
        return 1.0

    def is_used(self, candidate: ProviderAsset) -> bool:
        from agents.session_asset_registry import video_hash

        return self.registry.is_used(
            candidate.clip_id or "",
            candidate.download_url,
            video_hash(candidate.download_url),
        )
