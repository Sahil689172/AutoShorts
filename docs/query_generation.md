# Query Generation — Phase 2.2

**Date:** 2026-06-24  
**Component:** `agents/query_agent.py`  
**Consumer:** `VisualTimelineAgent` (active video pipeline)  

---

## Overview

Phase 2.2 replaces rule-based `keywords_from_description()` in the **active** visual pipeline with **Ollama-generated stock search queries**. Each scene now gets **3–5 concise queries** (max **4 words** each). Pexels/Pixabay are searched in query order until a match is found.

The legacy `VisualAssetAgent` still uses `keywords_from_description()` — it is not on the main render path.

---

## Architecture

```
scenes/scenes.json
  │  title, visual_description per scene
  ▼
QueryAgent.generate_queries()     ← Ollama (llama3)
  │  3-5 queries per scene
  ▼
VisualTimelineAgent._resolve_scene_asset()
  │  for each query (in order):
  │    1. Pexels Video API
  │    2. Pexels Image + Pixabay (parallel)
  ▼
First hit wins → download → FFmpeg render
```

### Dependency diagram

```
Scene title + visual_description
            │
            ▼
     ┌──────────────┐
     │  QueryAgent  │  (Ollama llama3)
     └──────┬───────┘
            │ queries: list[str]
            ▼
     ┌──────────────────────┐
     │ VisualTimelineAgent  │
     └──────────┬───────────┘
                │
    ┌───────────┼───────────┐
    ▼           ▼           ▼
 Pexels      Pexels       Pixabay
 Video       Images       Images
```

---

## QueryAgent API

### Input

| Field | Source |
|-------|--------|
| `title` | `scenes.json` → `title` |
| `visual_description` | `scenes.json` → `visual_description` |

### Output

`list[str]` — 3 to 5 queries, each ≤ 4 words.

### Example (from requirements)

**Input:**

- Title: `Turbocharger`
- Visual Description: `Close-up view of a turbocharger spinning rapidly inside a high-performance engine.`

**Output:**

```json
[
  "turbocharger close up",
  "engine internals",
  "performance engine",
  "automotive workshop",
  "turbo spinning"
]
```

### Example (automotive narration)

**Input:**

- Title: `Tractor Origins`
- Visual Description: `Vintage red tractor plowing a field on an Italian farm.`

**Likely output:**

```json
[
  "vintage red tractor",
  "tractor plowing field",
  "italian farm field",
  "farm equipment close",
  "agricultural tractor work"
]
```

---

## Ollama configuration

| Setting | Value |
|---------|-------|
| Model | `llama3` (default, same as SceneAgent) |
| Format | JSON (`{"queries": [...]}`) |
| Temperature | 0.2 |
| Max attempts | 2 |
| Fallback | `keywords_from_description()` chunked into short queries |

### Prompt rules (enforced in system prompt)

- 3–5 queries per scene
- Max 4 words per query
- Concrete, visual, searchable phrases
- Avoid generic terms (`car`, `vehicle`, `transportation`, `automobile`, etc.) unless the scene explicitly needs them

### Post-processing (`_sanitize_queries`)

- Lowercase normalization
- Deduplication
- Truncate to 4 words
- Filter overly generic queries via `GENERIC_TERMS` blocklist
- Pad with rule-based fallback if fewer than 3 queries remain

---

## VisualTimelineAgent integration

### Pipeline order (Phase 4.5B)

| Step | Action |
|------|--------|
| 1 | Read `scenes/scenes.json` |
| 2 | **Generate search queries** (`QueryAgent`) |
| 3 | Try topic cache restore (matches any generated query) |
| 4 | Parallel asset search + download |
| 5–8 | Render, mux audio, burn captions |

### SceneRecord fields

| Field | Purpose |
|-------|---------|
| `queries` | All generated queries |
| `query` | **Selected** query that produced the asset (cache key) |
| `selected_asset_url` | Download URL of chosen clip |

### Search strategy

For each scene, queries are tried **in order**:

1. **Pexels video** — `per_page=6`, portrait, top resolution score
2. **Pexels image + Pixabay** — parallel, per query
3. Next query if no hits

Early exit on first successful video; images only if no video matched any query.

### Logging

Per scene selection:

```
Scene N title: <title>
Scene N generated queries: ['query one', 'query two', ...]
Scene N selected query: <winning query>
Scene N selected asset: <url> (pexels_video|pexels_image|pixabay_image)
```

CLI also prints:

```
Scene 3 | selected query: 'turbocharger close up' | asset: pexels_video
```

---

## Comparison: old vs new

| Aspect | `keywords_from_description` | `QueryAgent` |
|--------|----------------------------|--------------|
| Engine | Rule-based stop-word filter | Ollama |
| Queries per scene | 1 (up to 8 words) | 3–5 (max 4 words each) |
| Semantic understanding | No | Yes (via LLM) |
| Generic term control | Stop words only | Prompt + blocklist |
| Fallback queries | N/A | Yes, tries next query |
| Latency | Instant | ~1–3s per scene (Ollama) |

### Old behavior example

Title: `Turbocharger`  
Description: `Close-up view of a turbocharger spinning rapidly inside a high-performance engine.`

**Old query (single string):**

```
turbocharger close view turbocharger spinning rapidly inside high performance
```

**New queries (illustrative):**

```
turbocharger close up | engine internals | performance engine | turbo spinning
```

---

## Files

| File | Role |
|------|------|
| `agents/query_agent.py` | `QueryAgent`, Ollama prompts, sanitization |
| `agents/visual_timeline_agent.py` | Integration, multi-query search, logging |
| `agents/visual_asset_agent.py` | Legacy `keywords_from_description()` (unchanged for legacy agent) |

---

## Requirements

- **Ollama** running locally (`ollama serve`)
- **llama3** model pulled (`ollama pull llama3`)
- **PEXELS_API_KEY** and/or **PIXABAY_API_KEY** in `.env`

---

## Troubleshooting

| Issue | Action |
|-------|--------|
| Slow asset phase | QueryAgent runs sequentially per scene before parallel search; expected +1–3s per scene |
| Generic queries still appear | Check scene `visual_description` quality from SceneAgent; review logs for fallback |
| Ollama connection error | Start Ollama; QueryAgent falls back to rule-based queries |
| No assets found | All queries exhausted — improve scene descriptions or add API keys |

---

## Future phases

| Phase | Enhancement |
|-------|-------------|
| 2.3 Semantic Search | Embed queries + results; relevance scoring beyond resolution |
| 2.4 Clip Ranking | Rank candidates by meaning, diversity, duration fit |

---

*End of Query Generation documentation*
