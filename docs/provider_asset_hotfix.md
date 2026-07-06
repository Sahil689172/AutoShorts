# ProviderAsset Compatibility Hotfix — Phase 3.1 / 3.2

**Date:** 2026-07-06  
**Status:** Fixed  

---

## Root cause

Phase 3.2 introduced `ProviderAsset` as the unified search result for the **generation pipeline** (`AssetProviderManager`, `ClipRanker`, `VisualTimelineAgent`).

Phase 3.1 **Asset Collection Engine** was written against an earlier inline model (`RemoteAsset`) that included library-specific fields such as `media_type`. After the refactor, `RemoteAsset` became an alias for `ProviderAsset`, but `ProviderAsset` did not carry every field the collector reads when building `AssetMetadata`.

First failure at runtime:

```
AttributeError: 'ProviderAsset' object has no attribute 'media_type'
```

in `asset_collector.py` when mapping a search hit to `AssetMetadata`.

---

## Field audit

### AssetCollector consumption (`ProviderAsset` → `AssetMetadata`)

| ProviderAsset field | Used by collector | Pre-3.2 expectation |
|---------------------|-------------------|---------------------|
| `download_url` | ✓ | ✓ |
| `provider` | ✓ | ✓ |
| `clip_id` | ✓ (as `provider_clip_id`) | ✓ |
| `width`, `height`, `duration` | ✓ | ✓ |
| `tags` | ✓ | ✓ |
| `photographer` | ✓ | ✓ |
| `media_type` | ✓ | ✓ **missing on ProviderAsset** |
| `source` | — (timeline uses separately) | ✓ on asset |
| `source_query` | — (collector uses loop query) | optional |
| `title`, `description` | — (ranking only) | optional |

### Not on ProviderAsset (by design)

| Field | Where it lives | Why |
|-------|----------------|-----|
| `asset_id` | Derived via `ProviderAsset.asset_id` or collector hash fallback | Computed, not provider-native |
| `search_query`, `topic`, `subtopic` | Collection context | Set by `AssetCollector`, not the API |
| `local_path`, `download_date` | `AssetMetadata` after storage | Post-download |
| `filename` | Derived from `asset_id` + extension at store time | Filesystem concern |
| `provider_id` | Same as `clip_id` | Renamed to `clip_id` in unified model |
| `orientation` | `ProviderAsset.orientation` property | Derived from width/height |
| `thumbnail` | Not required for collection or generation yet | Future provider field |

---

## Compatibility strategy

**Option A chosen:** extend `ProviderAsset` as the **single canonical asset representation** for both:

- Asset Provider Manager (generation)
- Asset Collection Engine (offline library growth)

No separate `CollectorAsset` or conversion layer — avoids duplicate models and drift between pipelines.

### Changes

1. **`ProviderAsset.media_type`** — default `"video"`; image providers set `"image"` when implemented.
2. **`ProviderAsset.orientation`** — read-only property (`portrait` / `landscape`) for ranking and clip intelligence.
3. **`PexelsProvider`** — sets `media_type="video"` on search results and cache round-trips.
4. **`ClipRanker._with_source_query`** — copies `media_type` when enriching candidates (frozen dataclass copy).

`RemoteAsset = ProviderAsset` remains for backward-compatible imports.

---

## Why future providers keep working

1. **Single contract** — every `AssetProvider.search()` returns `list[ProviderAsset]` with the same required technical fields (`download_url`, dimensions, duration, `clip_id`, `provider`, `media_type`).
2. **`get_metadata()`** — providers implement `AssetProvider.get_metadata(asset)` for index/library records; it reads from the same `ProviderAsset` instance.
3. **Pipeline-specific fields stay downstream** — collection adds `topic`, `subtopic`, and `search_query`; generation adds `source_query` via `_with_source_query`; neither pipeline mutates the provider model shape.
4. **Defaults are safe** — `media_type="video"` matches current Pexels-only video path; new providers override explicitly.

### Checklist for a new provider

```python
ProviderAsset(
    download_url=...,
    width=...,
    height=...,
    duration=...,
    clip_id=...,
    provider="my_provider",
    media_type="video",  # or "image"
    source="my_provider_video",
    ...
)
```

---

## Verification

```bash
python collect_assets.py
```

Collection should progress past search → metadata mapping → download → timeline placeholder write without `AttributeError`.

Generation pipeline (`VisualTimelineAgent`) is unchanged; it already used `ProviderAsset` fields only.

---

## Related docs

- [Provider Architecture](provider_architecture.md)
- [Asset Collection](asset_collection.md)
- [Clip Intelligence](clip_intelligence.md)
