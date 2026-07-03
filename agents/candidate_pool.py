"""Merge and deduplicate multi-query Pexels video search results."""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from agents.session_asset_registry import SessionAssetRegistry

logger = logging.getLogger(__name__)

RESULTS_PER_QUERY = 6
SCORE_SIMILARITY_RATIO = 0.05


class ScoredVideo(Protocol):
    clip_id: str
    url: str
    source: str

    def score(self) -> float: ...


@dataclass
class PoolStats:
    results_per_query: dict[str, int] = field(default_factory=dict)
    raw_total: int = 0
    pool_size: int = 0
    duplicate_count: int = 0


def merge_query_results(
    query_results: dict[str, list[ScoredVideo]],
) -> tuple[list[ScoredVideo], PoolStats]:
    """Merge per-query results into one deduplicated candidate pool."""
    stats = PoolStats()
    stats.results_per_query = {q: len(clips) for q, clips in query_results.items()}
    stats.raw_total = sum(stats.results_per_query.values())

    seen_ids: set[str] = set()
    seen_urls: set[str] = set()
    pool: list[ScoredVideo] = []

    for clips in query_results.values():
        for clip in clips:
            clip_id = getattr(clip, "clip_id", "") or ""
            url = clip.url
            is_dup = False
            if clip_id and clip_id in seen_ids:
                is_dup = True
            if url in seen_urls:
                is_dup = True
            if is_dup:
                stats.duplicate_count += 1
                continue
            if clip_id:
                seen_ids.add(clip_id)
            seen_urls.add(url)
            pool.append(clip)

    pool.sort(key=lambda c: c.score(), reverse=True)
    stats.pool_size = len(pool)
    return pool, stats


@dataclass(frozen=True)
class SelectionResult:
    candidate: ScoredVideo
    source_query: str
    previously_used: bool
    fallback_mode: bool
    reason: str


def _score_tolerance(top_score: float) -> float:
    return max(top_score * SCORE_SIMILARITY_RATIO, 1.0)


def select_best_candidate(
    pool: list[ScoredVideo],
    registry: SessionAssetRegistry,
    *,
    source_queries: dict[str, str] | None = None,
) -> SelectionResult | None:
    """
    Pick the best clip from a candidate pool with global diversity rules.

    source_queries maps clip url -> query that surfaced the clip.
    """
    if not pool:
        return None

    url_to_query = source_queries or {}

    def clip_hash(clip: ScoredVideo) -> str:
        return hashlib.sha256(clip.url.encode("utf-8")).hexdigest()[:16]

    def is_used(clip: ScoredVideo) -> bool:
        return registry.is_used(
            getattr(clip, "clip_id", "") or "",
            clip.url,
            clip_hash(clip),
        )

    unused = [c for c in pool if not is_used(c)]
    fallback = not unused
    candidates = unused if unused else pool

    if fallback:
        logger.warning("No unique clip available. Using highest-ranked previous clip.")

    top_score = max(c.score() for c in candidates)
    tolerance = _score_tolerance(top_score)
    tier = [c for c in candidates if top_score - c.score() <= tolerance]
    tier.sort(key=lambda c: (is_used(c), -c.score()))
    winner = tier[0]
    previously_used = is_used(winner)

    if fallback:
        reason = (
            "Fallback — all candidates already used in this video; "
            f"highest-ranked reuse (score={winner.score():.1f})"
        )
    elif len(tier) > 1 and top_score - tier[-1].score() <= tolerance:
        reason = (
            f"Highest score among {len(tier)} similar candidates within "
            f"{SCORE_SIMILARITY_RATIO:.0%} tolerance; preferred unused clip "
            f"(score={winner.score():.1f})"
        )
    else:
        reason = f"Highest resolution score among unique candidates (score={winner.score():.1f})"

    query = url_to_query.get(winner.url, getattr(winner, "source_query", "") or "")

    return SelectionResult(
        candidate=winner,
        source_query=query,
        previously_used=previously_used,
        fallback_mode=fallback,
        reason=reason,
    )
