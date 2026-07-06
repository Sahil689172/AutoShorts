# Clip Ranking — Phase 3.3

**Date:** 2026-07-06  
**Component:** `backend/services/assets/ranking/`  
**Consumer:** `VisualTimelineAgent._select_video_from_pool()`  

---

## Overview

Phase 3.3 replaces resolution-only winner selection with a **modular weighted ranking engine**. Each candidate in the pool receives five scores (0.0–1.0), combined into a final weighted score. The highest-scoring unused clip wins; session diversity rules are preserved.

---

## Ranking Pipeline

```
Candidate Pool (merged, deduplicated)
        │
        ▼
ClipRanker.rank()
  ├── SceneRankContext (title, visual_description, queries)
  ├── For each candidate:
  │     SemanticScorer    → 0.0–1.0
  │     PortraitScorer    → 0.0–1.0
  │     ResolutionScorer  → 0.0–1.0
  │     DurationScorer    → 0.0–1.0
  │     DiversityScorer   → 0.0–1.0  (session registry)
  │     └── weighted final score
  ├── Prefer unused candidates (diversity > 0)
  ├── Fallback if all previously used
  └── Ranking report + winner
        │
        ▼
Download winning clip only
```

### Before (Phase 2.3 / 3.2)

```
Pool → resolution heuristic score() → select_best_candidate()
```

### After (Phase 3.3)

```
Pool → ClipRanker.rank() → weighted multi-signal winner
```

---

## Scoring Modules

| Module | Signal | Range | Method (Phase 3.3) |
|--------|--------|-------|---------------------|
| **Semantic** | Relevance to scene | 0–1 | Token Jaccard overlap between scene context and asset metadata (query, tags, title, description) |
| **Portrait** | 9:16 fit | 0–1 | Aspect ratio deviation from 1080×1920 |
| **Resolution** | Pixel count | 0–1 | `width×height` vs 1080×1920 target |
| **Duration** | Trim suitability | 0–1 | Ideal 5–15 seconds |
| **Diversity** | Session uniqueness | 0–1 | 1.0 if unused in current video; 0.0 if in session registry |

All scorers implement the same interface and return **0.0–1.0**.

### Semantic scoring (no embeddings)

Uses available metadata:

- Scene: `title`, `visual_description`, generated `queries`
- Asset: `source_query`, `tags`, `title`, `description`, `photographer`

Plus a boost when `source_query` exactly matches a generated query.

**Future:** Replace `SemanticScorer` internals with CLIP/Ollama embedding cosine similarity without changing `ClipRanker.rank()` signature.

---

## Weight System

### Default weights

| Module | Weight |
|--------|--------|
| Semantic | 0.45 |
| Portrait | 0.15 |
| Resolution | 0.15 |
| Duration | 0.10 |
| Diversity | 0.15 |

Weights are normalized to sum to 1.0 before scoring.

### Configuration via environment

| Variable | Default |
|----------|---------|
| `RANK_WEIGHT_SEMANTIC` | 0.45 |
| `RANK_WEIGHT_PORTRAIT` | 0.15 |
| `RANK_WEIGHT_RESOLUTION` | 0.15 |
| `RANK_WEIGHT_DURATION` | 0.10 |
| `RANK_WEIGHT_DIVERSITY` | 0.15 |

```python
final = (
    w_semantic * semantic
    + w_portrait * portrait
    + w_resolution * resolution
    + w_duration * duration
    + w_diversity * diversity
)
```

---

## Integration

### VisualTimelineAgent

```python
ranking = self.clip_ranker.rank(
    title=scene.title,
    visual_description=scene.visual_description,
    queries=queries,
    pool=pool,
    registry=self.session_registry,
    source_queries=url_to_query,
    scene_number=scene.scene_number,
)
winner = ranking.winner
```

Replaces direct call to `select_best_candidate()` from `candidate_pool.py`.

### Unchanged downstream

| Component | Status |
|-----------|--------|
| Multi-query pool build | Unchanged |
| `merge_query_results()` | Unchanged |
| Session asset registry | Unchanged |
| Download pipeline | Unchanged |
| Image/Pixabay fallback | Unchanged |

---

## Ranking Report

Per scene, printed to console:

```
Scene 3 ranking report (Farm Equipment):
  Candidate      Semantic Portrait Resolution Duration Diversity    Final
  3847592            0.72     0.95       0.88     0.85      1.00    0.812
  1209843            0.55     0.90       0.92     0.70      1.00    0.701
  ...
  Winning clip: 3847592 (final=0.812, query='farm tools')
```

Logged fields per candidate: Semantic, Portrait, Resolution, Duration, Diversity, Final Score, Winning Clip.

---

## Package Layout

```
backend/services/assets/ranking/
├── __init__.py
├── clip_ranker.py       # ClipRanker.rank()
├── models.py            # SceneRankContext, CandidateScore, RankingResult
├── scorers.py           # Semantic, Portrait, Resolution, Duration, Diversity
└── weights.py           # RankWeights, load_rank_weights()
```

---

## Future Embedding Integration

### Planned upgrade path (Phase 3.4+)

1. Add `EmbeddingSemanticScorer` implementing the same `score(candidate, context) -> float` contract
2. Embed scene: `title + visual_description`
3. Embed asset: keyframe or provider description
4. Return `cosine_similarity(scene_vec, asset_vec)` clamped to 0–1
5. Inject via `ClipRanker(semantic_scorer=EmbeddingSemanticScorer(...))`

No changes required in:

- `VisualTimelineAgent`
- `AssetProviderManager`
- Candidate pool merge logic
- Weight configuration

```python
# Future
class EmbeddingSemanticScorer:
    def score(self, candidate, context) -> float:
        scene_vec = self.embedder.encode_scene(context)
        asset_vec = self.embedder.encode_asset(candidate)
        return cosine_similarity(scene_vec, asset_vec)
```

---

## Related Documentation

| Doc | Scope |
|-----|-------|
| `docs/multi_query_search.md` | Candidate pooling (Phase 2.3) |
| `docs/provider_architecture.md` | Provider abstraction (Phase 3.2) |
| `docs/autoshorts_v2_architecture.md` | Long-term asset intelligence vision |

---

*End of Clip Ranking documentation*
