"""Weighted multi-signal clip ranking for scene asset selection."""

from __future__ import annotations

import logging

from agents.session_asset_registry import SessionAssetRegistry
from backend.services.assets.providers.asset_provider import ProviderAsset
from backend.services.assets.ranking.models import (
    CandidateScore,
    RankingResult,
    SceneRankContext,
)
from backend.services.assets.ranking.scorers import (
    DiversityScorer,
    DurationScorer,
    PortraitScorer,
    ResolutionScorer,
    SemanticScorer,
)
from backend.services.assets.ranking.weights import RankWeights, load_rank_weights

logger = logging.getLogger(__name__)


class ClipRanker:
    """
    Rank candidate pool using modular scorers and configurable weights.

    Embedding-based semantic scoring can replace SemanticScorer without
    changing callers.
    """

    def __init__(
        self,
        weights: RankWeights | None = None,
        semantic_scorer: SemanticScorer | None = None,
        resolution_scorer: ResolutionScorer | None = None,
        portrait_scorer: PortraitScorer | None = None,
        duration_scorer: DurationScorer | None = None,
    ) -> None:
        self.weights = (weights or load_rank_weights()).normalized()
        self.semantic_scorer = semantic_scorer or SemanticScorer()
        self.resolution_scorer = resolution_scorer or ResolutionScorer()
        self.portrait_scorer = portrait_scorer or PortraitScorer()
        self.duration_scorer = duration_scorer or DurationScorer()

    def rank(
        self,
        *,
        title: str,
        visual_description: str,
        queries: list[str],
        pool: list[ProviderAsset],
        registry: SessionAssetRegistry,
        source_queries: dict[str, str] | None = None,
        scene_number: int = 0,
    ) -> RankingResult | None:
        if not pool:
            return None

        context = SceneRankContext(
            title=title,
            visual_description=visual_description,
            queries=list(queries),
            scene_number=scene_number,
        )
        url_to_query = source_queries or {}
        diversity_scorer = DiversityScorer(registry)

        scored: list[CandidateScore] = []
        for candidate in pool:
            source_query = url_to_query.get(
                candidate.url,
                candidate.source_query or "",
            )
            enriched = candidate
            if source_query and not candidate.source_query:
                enriched = _with_source_query(candidate, source_query)

            semantic = self.semantic_scorer.score(enriched, context)
            portrait = self.portrait_scorer.score(enriched, context)
            resolution = self.resolution_scorer.score(enriched, context)
            duration = self.duration_scorer.score(enriched, context)
            diversity = diversity_scorer.score(enriched, context)
            final = self.weights.weighted_total(
                semantic=semantic,
                portrait=portrait,
                resolution=resolution,
                duration=duration,
                diversity=diversity,
            )
            scored.append(
                CandidateScore(
                    candidate=enriched,
                    semantic=semantic,
                    portrait=portrait,
                    resolution=resolution,
                    duration=duration,
                    diversity=diversity,
                    final=final,
                    source_query=source_query,
                    previously_used=diversity_scorer.is_used(enriched),
                )
            )

        unused = [s for s in scored if s.diversity > 0]
        fallback = not unused
        candidates = unused if unused else scored

        if fallback:
            logger.warning("No unique clip available. Using highest-ranked previous clip.")

        candidates.sort(key=lambda s: s.final, reverse=True)
        winner = candidates[0]

        result = RankingResult(
            winner=winner,
            ranked=sorted(scored, key=lambda s: s.final, reverse=True),
            fallback_mode=fallback,
            scene_title=title,
        )
        self._log_ranking_report(result, scene_number)
        return result

    def _log_ranking_report(self, result: RankingResult, scene_number: int) -> None:
        print(f"\n  Scene {scene_number} ranking report ({result.scene_title}):", flush=True)
        print(
            f"  {'Candidate':<14} {'Semantic':>8} {'Portrait':>8} {'Resolution':>10} "
            f"{'Duration':>8} {'Diversity':>9} {'Final':>8}",
            flush=True,
        )
        for row in result.ranked:
            label = row.clip_label[:14]
            print(
                f"  {label:<14} {row.semantic:8.2f} {row.portrait:8.2f} "
                f"{row.resolution:10.2f} {row.duration:8.2f} {row.diversity:9.2f} "
                f"{row.final:8.3f}",
                flush=True,
            )
        w = result.winner
        print(
            f"  Winning clip: {w.clip_label} (final={w.final:.3f}, query={w.source_query!r})",
            flush=True,
        )
        if result.fallback_mode:
            print(
                "  No unique clip available. Using highest-ranked previous clip.",
                flush=True,
            )

        logger.info(
            "Scene %d ranking: winner=%s final=%.3f fallback=%s",
            scene_number,
            w.clip_label,
            w.final,
            result.fallback_mode,
        )


def _with_source_query(candidate: ProviderAsset, source_query: str) -> ProviderAsset:
    return ProviderAsset(
        download_url=candidate.download_url,
        width=candidate.width,
        height=candidate.height,
        duration=candidate.duration,
        clip_id=candidate.clip_id,
        source=candidate.source,
        provider=candidate.provider,
        photographer=candidate.photographer,
        source_query=source_query,
        tags=candidate.tags,
        title=candidate.title,
        description=candidate.description,
    )
