# Object Extraction — Phase 3.4

**Date:** 2026-07-06  
**Component:** `backend/services/scene_understanding/`  
**Consumer:** `VisualTimelineAgent` → `QueryAgent`  

---

## Overview

Phase 3.4 adds an **Object Extraction Engine** that identifies concrete visual objects from each scene before search query generation. Queries now target specific filmable subjects mentioned in narration rather than generic scene descriptions alone.

---

## Pipeline

### Before

```
Scene (title + visual_description)
    → QueryAgent
    → Search queries
```

### After

```
Scene (title + visual_description + narration segment)
    → ObjectExtractor
    → Primary / secondary objects, brands, locations, components, figures
    → QueryAgent (object-aware prompt)
    → Precise search queries
    → AssetProviderManager → ClipRanker → render
```

Rendering and provider architecture are **unchanged**.

---

## Object Extractor

**File:** `backend/services/scene_understanding/object_extractor.py`

### Input

| Field | Source |
|-------|--------|
| Scene title | `scenes.json` |
| Scene description | `scenes.json` → `visual_description` |
| Narration text | `scripts/script.txt` mapped per scene by duration |

### Output (`ExtractedObjects`)

| Category | Example |
|----------|---------|
| `primary_objects` | turbocharger, seatbelt |
| `secondary_objects` | engine bay, car interior |
| `brands` | Volvo, Ferrari |
| `locations` | Italy, factory floor |
| `mechanical_components` | compressor wheel, exhaust manifold |
| `historical_figures` | Ferruccio Lamborghini |

### Example 1

**Narration:** *"The turbocharger spins at over 200,000 RPM."*

**Objects:**
- turbocharger
- compressor wheel
- engine
- exhaust manifold

### Example 2

**Narration:** *"Volvo invented the three-point seatbelt."*

**Objects:**
- seatbelt
- Volvo
- car interior
- safety

---

## Narration Mapping

`scripts/script.txt` does not include per-scene narration. `narration_mapper.py` splits the full script **proportionally by scene duration** so each scene receives a narration excerpt for object extraction.

---

## QueryAgent Integration

When `ExtractedObjects` is provided, QueryAgent uses an object-aware prompt:

```
Extracted Visual Objects:
Primary objects: turbocharger, compressor wheel
Mechanical components: exhaust manifold
...

Use the extracted objects above to produce precise stock footage search queries.
```

Fallback query generation also prioritizes `primary_objects` and `mechanical_components`.

---

## Debug Output

Per scene during generation:

```
Scene 3 (Turbocharger)
  Objects: turbocharger, compressor wheel, engine, exhaust manifold
  Generated queries: ['turbocharger close up', 'compressor wheel spin', ...]
  Selected query (initial): 'turbocharger close up'
```

After ranking and selection:

```
  Selected query: 'turbocharger close up'
  Winning clip: pexels_3847592 (final=0.812, query='turbocharger close up')
```

---

## Package Layout

```
backend/services/scene_understanding/
├── __init__.py
├── models.py              # ExtractedObjects
├── object_extractor.py    # ObjectExtractor (Ollama)
└── narration_mapper.py    # Script → per-scene narration
```

---

## Integration Points

| Component | Change |
|-----------|--------|
| `VisualTimelineAgent` | `_extract_scene_objects()` before `_generate_search_queries()` |
| `QueryAgent` | Optional `extracted_objects` + `narration_text` parameters |
| `ClipRanker` | Unchanged (benefits from better queries indirectly) |
| `AssetProviderManager` | Unchanged |
| FFmpeg render | Unchanged |

---

## Ollama Requirements

- Local Ollama with `llama3` (same as SceneAgent / QueryAgent)
- Falls back to rule-based keyword extraction if Ollama fails

---

## Future Enhancements

| Phase | Enhancement |
|-------|-------------|
| 3.5+ | Per-scene narration in `scenes.json` from SceneAgent |
| 3.5+ | Object embeddings for semantic clip matching |
| 3.8 | Object-driven local library retrieval |

---

## Related Documentation

| Doc | Scope |
|-----|-------|
| `docs/query_generation.md` | QueryAgent (Phase 2.2) |
| `docs/clip_ranking.md` | ClipRanker (Phase 3.3) |
| `docs/provider_architecture.md` | Provider manager (Phase 3.2) |

---

*End of Object Extraction documentation*
