# Multi-Query Asset Search — Phase 2.3

**Date:** 2026-07-03  
**Components:** `agents/candidate_pool.py`, `agents/session_asset_registry.py`, `VisualTimelineAgent`  

---

## Overview

Phase 2.3 upgrades asset retrieval from **first-query-wins** to **multi-query candidate pooling**. Every AI-generated query is searched against Pexels Videos; results are merged, deduplicated, ranked with global diversity rules, and only then is a single clip selected for download.

---

## Architecture

### Before (Phase 2.2)

```
Scene → QueryAgent (3–5 queries)
     → try query 1 → Pexels → hit? stop
     → try query 2 → ...
     → download first hit
```

### After (Phase 2.3)

```
Scene → QueryAgent (3–5 queries)
     → search ALL queries in parallel (6 results each)
     → merge + dedupe by clip_id + URL
     → filter global session registry
     → rank + diversity select ONE clip
     → download selected clip only
```

### Full pipeline diagram

```
scenes.json
    │
    ▼
QueryAgent.generate_queries()          (Phase 2.2)
    │
    ▼
┌─────────────────────────────────────────────────────┐
│  _build_video_candidate_pool()  [parallel per scene]│
│    for each query → PexelsVideoClient.search(6)     │
│    merge_query_results() → dedupe pool              │
└──────────────────────┬──────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────┐
│  _select_video_from_pool()  [sequential by scene #]   │
│    filter SessionAssetRegistry                      │
│    select_best_candidate() → diversity + fallback   │
│    register winner in session registry              │
└──────────────────────┬──────────────────────────────┘
                       │
                       ▼
              _download_scene_asset()     (unchanged — one clip per scene)
                       │
                       ▼
                 FFmpeg render
```

---

## Candidate pooling strategy

### Per-query search

| Setting | Value |
|---------|-------|
| Provider | Pexels Videos only (pool phase) |
| Results per query | **6** (`RESULTS_PER_QUERY`) |
| Orientation | Portrait |
| Min resolution | 720×1080 |
| Min duration | 3 seconds |

### Merge and deduplicate

For each scene, all query results are combined. A clip is a duplicate if:

- **clip_id** (Pexels video `id`) already seen, or
- **download URL** already seen

When duplicates are found, the first occurrence (highest query order / merge order) is kept.

**Example:**

| Query | Results |
|-------|---------|
| `turbocharger close up` | 6 clips |
| `engine internals` | 6 clips |
| `performance engine` | 6 clips |
| **Raw total** | 18 |
| **Duplicates** | 2 |
| **Pool size** | 16 |

### Selection (pre-rus ranking)

Current ranking uses existing `VideoCandidate.score()`:

- Resolution (width × height)
- Portrait bonus (+30%)
- 1080×1920 bonus (+15%)
- Duration ≥ 8s bonus (+5%)

**Phase 2.4** will replace this with semantic relevance scoring over the full pool.

---

## Global asset diversity

### Session registry

File: `assets/session_asset_registry.json`

Reset at the start of each `VisualTimelineAgent.generate()` call.

```json
{
  "session_started_at": "2026-07-03T14:00:00+00:00",
  "assets": [
    {
      "clip_id": "3847592",
      "source": "pexels_video",
      "download_url": "https://videos.pexels.com/...",
      "scene_number": 1,
      "video_hash": "a1b2c3d4e5f67890"
    }
  ]
}
```

### Filtering rules

Before ranking, candidates matching any registry entry by **clip_id**, **download URL**, or **video_hash** are excluded from the primary selection path.

### Diversity preference

When multiple candidates have scores within **5%** of the top score, prefer clips **not previously used** in the current video.

### Fallback mode

If every candidate in the pool was already used:

```
No unique clip available. Using highest-ranked previous clip.
```

The highest-scored clip from the full pool is selected and logged as `Previously Used: YES`.

---

## Logging

### Per-scene pool log

```
Scene 3 (Farm Equipment) | pool: 14 clips (4 dupes) | per query: 'farm tools': 6, 'barn interior': 5, ...
```

Structured logs:

- `Scene N generated queries`
- `Scene N results per query`
- `Scene N candidate pool size`
- `Scene N duplicate count`

### Per-scene selection log

```
Scene 3 | clip id: 3847592 | Previously Used: NO | query: 'farm tools'
  Reason: Highest resolution score among unique candidates (score=2488320.0)
```

Fallback example:

```
No unique clip available. Using highest-ranked previous clip.
Scene 4 | clip id: 3847592 | Previously Used: YES | query: 'tractor field'
  Reason: Fallback — all candidates already used in this video; highest-ranked reuse (score=2100000.0)
```

---

## Performance impact

| Aspect | Phase 2.2 | Phase 2.3 |
|--------|-----------|-----------|
| Pexels calls per scene | 1–5 (early exit) | **3–5 always** (all queries) |
| Results fetched | up to 6 | **up to 30** (5 queries × 6) |
| API latency | Lower (stop early) | Higher (full search) |
| Selection quality | First acceptable hit | Best from merged pool |
| Cross-scene duplicates | Possible | Prevented via registry |
| Download count | 1 per scene | **1 per scene** (unchanged) |

Search cache (`SearchCache`, 24h TTL) reduces repeated API cost for identical queries across runs.

**Selection is sequential by scene number** to enforce global deduplication. Pool building remains parallel across scenes.

---

## Download pipeline (preserved)

1. Search and selection set `pending_url` / `pending_ext` only
2. `_download_scene_asset()` runs in parallel after all scenes are resolved
3. Only the final selected clip is downloaded per scene

No change to FFmpeg render, topic cache, or file cache behavior.

---

## Image fallback

If the video candidate pool is empty (no Pexels video API key, zero results, or all filtered), the legacy per-query **Pexels image + Pixabay** fallback runs. Image fallback is unchanged from Phase 2.2.

---

## Files

| File | Role |
|------|------|
| `agents/candidate_pool.py` | Merge, dedupe, rank, diversity selection |
| `agents/session_asset_registry.py` | Global clip registry per video |
| `agents/visual_timeline_agent.py` | Pool build, selection, logging integration |
| `assets/session_asset_registry.json` | Persisted registry (reset each run) |

---

## Future ranking integration (Phase 2.4)

The candidate pool is designed as input to a semantic ranker:

```python
pool = build_video_candidate_pool(scene)   # Phase 2.3
ranked = semantic_ranker.rank(pool, scene) # Phase 2.4
winner = diversity_select(ranked, registry)
```

Phase 2.3 intentionally keeps resolution-based scoring as the interim ranker so Phase 2.4 can plug in without changing search or pooling logic.

---

*End of Multi-Query Asset Search documentation*
