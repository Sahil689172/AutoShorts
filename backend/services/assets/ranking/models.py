"""Ranking models and result types."""

from __future__ import annotations

from dataclasses import dataclass, field

from backend.services.assets.providers.asset_provider import ProviderAsset


@dataclass(frozen=True)
class SceneRankContext:
    """Scene metadata passed into the ranker."""

    title: str
    visual_description: str
    queries: list[str]
    scene_number: int = 0


@dataclass(frozen=True)
class CandidateScore:
    """Per-candidate scoring breakdown (all values 0.0–1.0)."""

    candidate: ProviderAsset
    semantic: float
    portrait: float
    resolution: float
    duration: float
    diversity: float
    final: float
    source_query: str = ""
    previously_used: bool = False

    @property
    def clip_label(self) -> str:
        return self.candidate.clip_id or self.candidate.asset_id


@dataclass
class RankingResult:
    """Output of ClipRanker.rank()."""

    winner: CandidateScore
    ranked: list[CandidateScore] = field(default_factory=list)
    fallback_mode: bool = False
    scene_title: str = ""

    @property
    def reason(self) -> str:
        w = self.winner
        if self.fallback_mode:
            return (
                f"Fallback — all candidates previously used; "
                f"best weighted score={w.final:.3f}"
            )
        return (
            f"ClipRanker winner (final={w.final:.3f}): "
            f"semantic={w.semantic:.2f} portrait={w.portrait:.2f} "
            f"resolution={w.resolution:.2f} duration={w.duration:.2f} "
            f"diversity={w.diversity:.2f}"
        )
