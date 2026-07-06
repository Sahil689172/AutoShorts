# Provider Architecture — Phase 3.2

**Date:** 2026-07-06  
**Scope:** Unified asset provider abstraction for the generation pipeline  
**Status:** Implemented  

---

## Overview

Phase 3.2 replaces direct Pexels API calls inside `VisualTimelineAgent` with a **provider abstraction layer**. The generation workflow, multi-query search, candidate pooling, session registry, and ranking are unchanged.

```
VisualTimelineAgent
        │
        ▼
AssetProviderManager
        │
        ▼
AssetProvider (interface)
        │
        ├── PexelsProvider          ← enabled (production)
        ├── LocalLibraryProvider    ← future (disabled)
        ├── PixabayProvider         ← future (disabled)
        └── ArchiveProvider         ← future (disabled)
```

The offline **collection engine** (`collect_assets.py`) shares the same `PexelsProvider` and `AssetProvider` interface.

---

## Provider Interface

**File:** `backend/services/assets/providers/asset_provider.py`

### `ProviderAsset`

Unified candidate returned by all providers. Compatible with:

- `agents/candidate_pool.py` (`ScoredVideo` protocol via `.url`, `.clip_id`, `.score()`)
- `agents/session_asset_registry.py`
- `VideoCandidate` alias in `VisualTimelineAgent`

| Field | Purpose |
|-------|---------|
| `download_url` | Remote file URL |
| `clip_id` | Provider-native ID (Pexels video `id`) |
| `width`, `height`, `duration` | Technical metadata |
| `source` | Timeline source kind (`pexels_video`) |
| `provider` | Provider name (`pexels`) |
| `source_query` | Query that surfaced this asset |

### `AssetProvider` (abstract)

| Method | Responsibility |
|--------|----------------|
| `is_configured()` | API keys / prerequisites present |
| `search(query, per_page=6)` | Return ranked `ProviderAsset` list |
| `download(asset, dest, session)` | Persist remote file locally |
| `get_metadata(asset)` | Return `AssetProviderMetadata` |

### `AssetProviderMetadata`

Structured metadata record for indexing and future library integration.

---

## Pexels Provider

**File:** `backend/services/assets/providers/pexels_provider.py`

Contains all logic previously in `PexelsVideoClient` inside `visual_timeline_agent.py`:

| Behavior | Preserved |
|----------|-----------|
| Portrait orientation filter | ✓ |
| `per_page` results (default 6) | ✓ |
| Min 720×1080, duration ≥ 3s | ✓ |
| Best MP4 file selection | ✓ |
| Resolution-based sort | ✓ |
| `SearchCache` (`pexels_video` key, 24h TTL) | ✓ |
| `APIKeyMissingError` on missing key | ✓ |

No functional changes to Pexels search results or scoring.

---

## Provider Manager

**File:** `backend/services/assets/asset_provider_manager.py`

### Responsibilities

1. Instantiate **enabled** providers (currently `pexels` only)
2. Receive search requests from `VisualTimelineAgent`
3. Call each enabled provider's `search()`
4. Merge results with deduplication by `clip_id` and `download_url`
5. Return unified, score-sorted candidate list

### Configuration

```python
DEFAULT_ENABLED_PROVIDERS = ("pexels",)
```

Future providers are registered in `_build_providers()` but commented out until implemented.

### Usage in generation

```python
# VisualTimelineAgent.__init__
self.provider_manager = AssetProviderManager(search_cache=self.search_cache)

# _build_video_candidate_pool
clips = self.provider_manager.search(query, per_page=RESULTS_PER_QUERY)
```

Image fallback (Pexels images + Pixabay) remains in `VisualTimelineAgent._resolve_image_fallback()` — not part of the video provider manager in Phase 3.2.

---

## Generation Flow (unchanged behavior)

```
scenes.json
    │
    ▼
QueryAgent.generate_queries()          per scene
    │
    ▼
For each query (parallel):
    AssetProviderManager.search()
        └── PexelsProvider.search()
    │
    ▼
merge_query_results()                  candidate pool
    │
    ▼
select_best_candidate()                + SessionAssetRegistry
    │
    ▼
_download_scene_asset()                single clip per scene
    │
    ▼
FFmpeg render
```

---

## Package Layout

```
backend/services/assets/
├── asset_provider_manager.py      # Generation entry point
├── collector/                     # Offline collection (Phase 3.1)
├── library/
├── metadata/
├── cache/
├── utils/
└── providers/
    ├── asset_provider.py          # Interface + ProviderAsset
    ├── pexels_provider.py         # Pexels implementation
    └── registry.py                # Collection provider registry
```

---

## Adding a Future Provider

### 1. Implement `AssetProvider`

```python
# backend/services/assets/providers/local_library_provider.py

class LocalLibraryProvider(AssetProvider):
    name = "local_library"

    def is_configured(self) -> bool:
        return LIBRARY_ROOT.is_dir()

    def search(self, query: str, *, per_page: int = 6) -> list[ProviderAsset]:
        ...

    def download(self, asset, dest, session=None) -> Path:
        shutil.copy2(asset.local_path, dest)

    def get_metadata(self, asset) -> AssetProviderMetadata:
        ...
```

### 2. Register in `AssetProviderManager._build_providers()`

```python
elif key == "local_library":
    instances.append(LocalLibraryProvider())
```

### 3. Enable in `DEFAULT_ENABLED_PROVIDERS`

```python
DEFAULT_ENABLED_PROVIDERS = ("local_library", "pexels")
```

### 4. No changes to `VisualTimelineAgent`

The timeline agent only calls `provider_manager.search()`. New providers are picked up automatically.

---

## Separation of Concerns

| Subsystem | Entry point | Providers |
|-----------|-------------|-----------|
| **Video generation** | `AssetProviderManager` | Pexels video (enabled) |
| **Image fallback** | `VisualTimelineAgent` | `PexelsClient`, `PixabayClient` (legacy clients) |
| **Offline collection** | `AssetCollector` | `registry.resolve_providers()` |

---

## Compatibility Matrix

| Component | Phase 3.2 status |
|-----------|------------------|
| Multi-query search | Unchanged |
| Candidate pool merge/dedup | Unchanged |
| Session asset registry | Unchanged |
| Resolution ranking | Unchanged (on `ProviderAsset.score()`) |
| Topic cache | Unchanged |
| Download pipeline | Unchanged |
| CLI `main.py` / API pipeline | Unchanged |
| `collect_assets.py` | Uses shared `PexelsProvider` |

---

## Removed / Deprecated

| Item | Replacement |
|------|-------------|
| `PexelsVideoClient` in `visual_timeline_agent.py` | `PexelsProvider` + `AssetProviderManager` |
| `providers/base.py` | `asset_provider.py` |
| `providers/pexels.py` (collection-only) | `pexels_provider.py` (shared) |

---

*End of Provider Architecture documentation*
