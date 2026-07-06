"""Configurable weights for clip ranking modules."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class RankWeights:
    semantic: float = 0.45
    portrait: float = 0.15
    resolution: float = 0.15
    duration: float = 0.10
    diversity: float = 0.15

    def normalized(self) -> RankWeights:
        total = (
            self.semantic
            + self.portrait
            + self.resolution
            + self.duration
            + self.diversity
        )
        if total <= 0:
            return RankWeights()
        return RankWeights(
            semantic=self.semantic / total,
            portrait=self.portrait / total,
            resolution=self.resolution / total,
            duration=self.duration / total,
            diversity=self.diversity / total,
        )

    def weighted_total(
        self,
        *,
        semantic: float,
        portrait: float,
        resolution: float,
        duration: float,
        diversity: float,
    ) -> float:
        w = self.normalized()
        return (
            w.semantic * semantic
            + w.portrait * portrait
            + w.resolution * resolution
            + w.duration * duration
            + w.diversity * diversity
        )


def load_rank_weights() -> RankWeights:
    """Load weights from environment with documented defaults."""

    def _float(name: str, default: float) -> float:
        raw = os.environ.get(name, "").strip()
        if not raw:
            return default
        try:
            return float(raw)
        except ValueError:
            return default

    return RankWeights(
        semantic=_float("RANK_WEIGHT_SEMANTIC", 0.45),
        portrait=_float("RANK_WEIGHT_PORTRAIT", 0.15),
        resolution=_float("RANK_WEIGHT_RESOLUTION", 0.15),
        duration=_float("RANK_WEIGHT_DURATION", 0.10),
        diversity=_float("RANK_WEIGHT_DIVERSITY", 0.15),
    ).normalized()
