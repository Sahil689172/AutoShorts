# Asset Pipeline Audit — Phase 2.1

**Date:** 2026-06-24  
**Scope:** Visual asset selection from topic through final video render  
**Method:** Read-only codebase analysis — no code modified  

---

## Executive Summary

AutoShorts does **not** search stock footage using the topic or raw script directly. The active pipeline is:

1. **Ollama** splits the narration script into timed scenes with `title` + `visual_description`
2. **Rule-based keyword extraction** (`keywords_from_description`) turns each scene into a Pexels/Pixabay query string
3. **`VisualTimelineAgent`** searches **Pexels videos first**, then Pexels images + Pixabay in parallel, picks **one top-scored result per scene**, downloads it, and FFmpeg-renders a timeline

Footage often fails to match narration because: queries are generic bag-of-words keywords (not semantic), ranking favors resolution/portrait over relevance, Pexels API order is opaque, and there is **no script-to-clip semantic matching** — only indirect LLM scene descriptions.

---

## 1. End-to-End Flow

```
Topic
  │
  ▼
ScriptGenerator (Ollama) ──────────────────► scripts/script.txt
  │
  ▼
VoiceGenerator / CaptionGenerator / SceneAgent
  │
  ▼
SceneAgent (Ollama) ───────────────────────► scenes/scenes.json
  │   • scene_number, duration_seconds,
  │     title, visual_description
  ▼
VisualTimelineAgent._read_scenes()
  │   keywords_from_description(title, visual_description) → query
  ▼
Per scene (parallel):
  │   1. Pexels Video API  (per_page=6, portrait)
  │   2. if miss → Pexels Image + Pixabay (parallel, per_page=6 each)
  │   3. rank by resolution score → candidates[0]
  │   4. HTTP GET download → assets/timeline/scene_N.mp4|.jpg
  ▼
FFmpeg: per-scene segments → concat → mux audio + burn SRT
  │
  ▼
videos/output.mp4
```

**Active entry points:** `main.py` (CLI), `backend/pipeline_runner._phase_visual_timeline()` (API)

**Legacy (not in active pipeline):** `VisualAssetAgent` (images only → `assets/scenes/`), `TimelineVideoBuilder`, `VideoGenerator`

---

## 2. Dependency Diagram

```
                    ┌─────────────────┐
                    │     Topic       │
                    └────────┬────────┘
                             │
              ┌──────────────▼──────────────┐
              │   ScriptGenerator (Ollama) │
              └──────────────┬──────────────┘
                             │
                    scripts/script.txt
                             │
         ┌───────────────────┼───────────────────┐
         │                   │                   │
         ▼                   ▼                   ▼
  VoiceGenerator      CaptionGenerator      SceneAgent (Ollama)
         │                   │                   │
  audio/output.wav    captions/output.srt   scenes/scenes.json
         │                   │                   │
         └───────────────────┼───────────────────┘
                             │
              ┌──────────────▼──────────────────────────┐
              │         VisualTimelineAgent              │
              │  keywords_from_description() per scene   │
              └──────────────┬──────────────────────────┘
                             │
                    Search Query (per scene)
                             │
         ┌───────────────────┼───────────────────┐
         ▼                   ▼                   ▼
  Pexels Videos API   Pexels Images API    Pixabay API
  (primary)           (fallback)           (fallback)
         │                   │                   │
         └───────────────────┼───────────────────┘
                             │
                    Clip Selection (score rank)
                             │
                    Download → assets/timeline/
                             │
              ┌──────────────▼──────────────┐
              │  FFmpeg segment + concat    │
              │  + audio mux + subtitles    │
              └──────────────┬──────────────┘
                             │
                    videos/output.mp4
```

---

## 3. Files Involved

### Orchestration

| File | Role |
|------|------|
| `main.py` | CLI pipeline; instantiates `SceneAgent`, `VisualTimelineAgent` |
| `backend/pipeline_runner.py` | API jobs; `_phase_scenes()`, `_phase_visual_timeline()` |
| `pipeline_timing.py` | `PHASE_SCENES`, `PHASE_ASSET_SEARCH`, `PHASE_VIDEO` labels |

### Script generation (upstream)

| File | Role |
|------|------|
| `script_generator.py` | Topic → `scripts/script.txt` via Ollama |

### Scene planning (search query source)

| File | Role |
|------|------|
| `agents/scene_agent.py` | Script + audio duration → `scenes/scenes.json` via Ollama |

### Asset search, download, render (active)

| File | Role |
|------|------|
| `agents/visual_timeline_agent.py` | **Primary** — search, download, FFmpeg render |
| `agents/visual_asset_agent.py` | Shared clients + `keywords_from_description()`; legacy `VisualAssetAgent` |
| `agents/topic_cache.py` | Topic-keyed asset reuse |
| `agents/timeline_video_builder.py` | Shared FFmpeg helpers (`probe_duration`, `build_motion_filter`, etc.) |
| `agents/subtitle_config.py` | Subtitle burn-in styles (render phase) |

### Legacy / unused in main path

| File | Role |
|------|------|
| `agents/visual_asset_agent.py` → `VisualAssetAgent` | Image-only downloader (not called by `main.py`) |
| `agents/timeline_video_builder.py` → `TimelineVideoBuilder` | Legacy image-motion renderer |
| `video_generator.py` | Background-video renderer (unused) |

### Config / docs

| File | Role |
|------|------|
| `.env` | `PEXELS_API_KEY`, `PIXABAY_API_KEY` |
| `Readme.md` | API key documentation |

### Generated artifacts

| Path | Producer |
|------|----------|
| `scripts/script.txt` | `ScriptGenerator` |
| `scenes/scenes.json` | `SceneAgent` |
| `assets/cache/*.json` | `SearchCache` (24h API result cache) |
| `assets/timeline/scene_N.mp4\|.jpg` | `VisualTimelineAgent` |
| `assets/cache/topics/{hash}/` | `TopicAssetCache` |
| `videos/output.mp4` | `VisualTimelineAgent` |

---

## 4. Classes and Functions

### `script_generator.py`

| Symbol | Description |
|--------|-------------|
| `ScriptGenerator.generate_and_save(topic)` | Writes narration from topic |

### `agents/scene_agent.py`

| Symbol | Description |
|--------|-------------|
| `SceneAgent` | Main scene planner |
| `SceneAgent.generate()` | Full phase: read script → analyze duration → Ollama → write JSON |
| `SceneAgent._analyze_duration()` | ffprobe on WAV or word-count estimate |
| `SceneAgent._generate_scenes()` | Ollama chat with `SYSTEM_PROMPT` / `USER_PROMPT_TEMPLATE` |
| `calculate_visual_segment_counts()` | ~1 scene per 5s, clamp 6–15 |
| `probe_audio_duration()` | ffprobe narration length |
| `estimate_duration_from_script()` | Fallback: `max(30, min(45, words/2.5))` |
| `parse_scenes_json()`, `enforce_scene_count()`, `normalize_scene_durations()` | Validation / timing normalization |

### `agents/visual_asset_agent.py`

| Symbol | Description |
|--------|-------------|
| **`keywords_from_description()`** | **Search query builder** (rule-based) |
| `PexelsClient` | Image search `GET /v1/search` |
| `PixabayClient` | Image search `GET /api/` |
| `SearchCache` | 24h file cache for API responses |
| `ImageCandidate.score()` | Resolution-based ranking |
| `VisualAssetAgent` | Legacy image-only pipeline |

### `agents/visual_timeline_agent.py`

| Symbol | Description |
|--------|-------------|
| `VisualTimelineAgent` | **Active video pipeline** |
| `VisualTimelineAgent.generate()` | Read scenes → search → download → render → mux |
| `VisualTimelineAgent._read_scenes()` | Load JSON, build `SceneRecord.query` via `keywords_from_description` |
| `VisualTimelineAgent._normalize_durations()` | Scale scene lengths to match narration WAV |
| `VisualTimelineAgent._resolve_scene_asset()` | Provider cascade + selection |
| `VisualTimelineAgent._download_scene_asset()` | HTTP download to `assets/timeline/` |
| `PexelsVideoClient` | Video search `GET /v1/videos/search` |
| `VideoCandidate.score()` | Resolution/duration ranking |
| `PexelsVideoClient._best_video_file()` | Pick largest MP4 from `video_files[]` |
| `_render_video_segment()`, `_render_image_segment()` | Per-scene FFmpeg |
| `_concat_segments()`, `_finalize_with_audio_and_subtitles()` | Final MP4 |

### `agents/topic_cache.py`

| Symbol | Description |
|--------|-------------|
| `TopicAssetCache.try_restore_scene()` | Reuse asset if same topic + same query |
| `TopicAssetCache.save_scene()` | Persist after successful download |

---

## 5. API Calls

### Pexels — Videos (primary)

| Property | Value |
|----------|-------|
| **URL** | `https://api.pexels.com/v1/videos/search` |
| **Class** | `PexelsVideoClient.search()` |
| **Auth** | Header `Authorization: {PEXELS_API_KEY}` |
| **Params** | `query`, `per_page=6`, `orientation=portrait` |
| **Filters** | duration ≥ 3s, MP4, min 720×1080 |
| **Response use** | `videos[]` → `video_files[]`, `duration`, `user.name` |

### Pexels — Images (fallback)

| Property | Value |
|----------|-------|
| **URL** | `https://api.pexels.com/v1/search` |
| **Class** | `PexelsClient.search()` |
| **Params** | `query`, `per_page=6`, `orientation=portrait` |
| **Filters** | min 1080×1080, valid URL in `src` |
| **Response use** | `photos[]` → `src.original|large2x|large|portrait` |

### Pixabay — Images (fallback)

| Property | Value |
|----------|-------|
| **URL** | `https://pixabay.com/api/` |
| **Class** | `PixabayClient.search()` |
| **Params** | `key`, `q`, `image_type=photo`, `orientation=vertical`, `per_page=6`, `min_width/min_height=1080`, `safesearch=true` |
| **Response use** | `hits[]` → `largeImageURL|fullHDURL|webformatURL` |

### Download (direct HTTP)

| Property | Value |
|----------|-------|
| **Method** | `requests.Session.get(url, stream=True)` |
| **Timeout** | 30 seconds |
| **Min size** | 50 KB (images), 100 KB (videos) |
| **User-Agent** | `YT-Agent/1.0 (visual-timeline-agent)` |

### Not used for search

- Topic string
- Raw script text (except indirectly via SceneAgent LLM)
- Sentence-level embeddings
- Pexels relevance score (not exposed in selection logic)

---

## 6. Configuration Variables

### Environment variables

| Variable | Used by | Default / notes |
|----------|---------|-----------------|
| `PEXELS_API_KEY` | `PexelsClient`, `PexelsVideoClient` | Required for Pexels |
| `PIXABAY_API_KEY` | `PixabayClient` | Required for Pixabay fallback |
| `ASSET_SEARCH_WORKERS` | `VisualTimelineAgent` | **12** — parallel scene searches |
| `ASSET_DOWNLOAD_WORKERS` | `VisualTimelineAgent` | **10** — parallel downloads |
| `FFMPEG_EXECUTABLE` | Render agents | PATH fallback |
| `FFPROBE_EXECUTABLE` | Duration probing | PATH fallback |

### Hardcoded constants

| Constant | File | Value |
|----------|------|-------|
| `SECONDS_PER_VISUAL` | `scene_agent.py` | 5 |
| `ABSOLUTE_MIN_SCENES` / `MAX` | `scene_agent.py` | 6 / 15 |
| `MIN_SCENE_DURATION` / `MAX` | `scene_agent.py` | 3 / 8 seconds |
| `MIN_IMAGE_WIDTH/HEIGHT` | `visual_asset_agent.py` | 1080 / 1080 |
| `MIN_VIDEO_WIDTH/HEIGHT` | `visual_timeline_agent.py` | 720 / 1080 |
| `MIN_VIDEO_DURATION` | `visual_timeline_agent.py` | 3 seconds |
| `CACHE_TTL_SECONDS` | `visual_asset_agent.py` | 24 hours |
| `REQUEST_TIMEOUT` | Both agents | 30 seconds |
| `DEFAULT_MODEL` | `scene_agent.py` | `llama3` |
| `VIDEO_WIDTH/HEIGHT/FPS` | `timeline_video_builder.py` | 1080×1920 @ 30fps |
| `MOTION_EFFECTS` | `timeline_video_builder.py` | zoom/pan/ken_burns (images only) |

---

## 7. What Does the System Search With?

| Input type | Used for stock search? | How |
|------------|------------------------|-----|
| **Topic** | **No** (directly) | Only for `TopicAssetCache` key and script generation |
| **Script** | **Indirectly** | Fed to SceneAgent Ollama prompt only |
| **Keywords** | **Yes** | Extracted from scene `title` + `visual_description` |
| **Sentences** | **No** | Not passed to APIs |
| **AI-generated queries** | **Partially** | Scene *descriptions* are AI-generated; search *strings* are deterministic keyword extraction |
| **Scene titles** | **Yes** | Concatenated into keyword input |

### Search query generation (`keywords_from_description`)

```108:123:agents/visual_asset_agent.py
def keywords_from_description(visual_description: str, title: str = "") -> str:
    """Build a concise stock-photo search query from scene text."""
    text = f"{title} {visual_description}".lower()
    text = re.sub(r"[^\w\s]", " ", text)
    words = [word for word in text.split() if len(word) > 2 and word not in STOP_WORDS]
    if not words:
        words = visual_description.split()[:6]
    unique: list[str] = []
    seen: set[str] = set()
    for word in words:
        if word not in seen:
            seen.add(word)
            unique.append(word)
        if len(unique) >= 8:
            break
    return " ".join(unique[:8])
```

**Characteristics:**
- Stop-word removal (~60 common English words)
- Max **8** unique keywords
- No quoting, no phrase preservation, no entity linking
- No synonym expansion or automotive domain vocabulary

---

## 8. Clip Selection Logic

### Provider priority (`_resolve_scene_asset`)

```
1. Pexels video search → if any hit: use top scored → STOP
2. Else parallel:
     - Pexels image search
     - Pixabay image search
3. Prefer Pexels image over Pixabay
4. If all miss: scene has no asset → pipeline fails
```

### How many API results fetched?

| Level | Count |
|-------|-------|
| Scenes per video | **6–15** (from narration duration ÷ ~5s) |
| API `per_page` per search | **6** |
| Clips downloaded per scene | **1** |
| Max searches per scene | 1–3 (video; then image + pixabay) |

### Ranking (not semantic relevance)

**Images** — `ImageCandidate.score()`:
- Base: `width × height`
- ×1.25 if portrait
- ×1.10 if ≥1080×1920

**Videos** — `VideoCandidate.score()`:
- Base: `width × height`
- ×1.30 if portrait
- ×1.15 if ≥1080×1920
- ×1.05 if duration ≥ 8s

After scoring: `candidates.sort(reverse=True)` → **`candidates[0]`** used.

**Not considered:** Pexels relevance rank, script alignment, duplicate detection across scenes, clip content labels, narration timing fit beyond duration trim.

### Video file pick within a Pexels result

`PexelsVideoClient._best_video_file()` — highest `width × height` MP4 link.

### Image motion

Random effect from `MOTION_EFFECTS` assigned per image scene (`zoom_in`, `pan_left`, `ken_burns`, etc.).

### Duration handling

- Scene durations from Ollama normalized to sum = narration length (`_normalize_durations`)
- Video segments trimmed/looped to `scene.duration_seconds` in `_render_video_segment`
- No verification that clip content matches the spoken words in that time window

---

## 9. Sample Script Walkthrough

**Script:** `"Lamborghini started as a tractor company before building supercars."`

### Step 1 — Script generation

If topic were `"Lamborghini tractor history"`, `ScriptGenerator` would expand to ~80–100 words. The one-line script above is valid input but **short**; scene timing still assumes **minimum 30s** narration when audio probe unavailable:

```165:168:agents/scene_agent.py
def estimate_duration_from_script(script: str) -> float:
    word_count = len(script.split())
    return max(30.0, min(45.0, word_count / WORDS_PER_SECOND_ESTIMATE))
```

10 words → estimated **30 seconds** → `calculate_visual_segment_counts(30)` → **6 scenes** (minimum).

### Step 2 — SceneAgent (Ollama) — illustrative output

Ollama output is **non-deterministic**. A plausible `scenes/scenes.json` for this script:

| # | title | visual_description | duration_s |
|---|-------|-------------------|------------|
| 1 | Tractor Origins | Vintage red tractor plowing a field on an Italian farm | 5 |
| 2 | Ferruccio's Vision | 1960s Italian factory floor with machinery and workers | 5 |
| 3 | Customer Dispute | Luxury sports car and tractor parked side by side in a garage | 5 |
| 4 | First Lamborghini | Sleek orange supercar driving on a winding mountain road | 5 |
| 5 | Brand Evolution | Modern Lamborghini showroom with bright LED lighting | 5 |
| 6 | Supercar Legacy | Close-up of Lamborghini logo on a matte black hypercar | 5 |

### Step 3 — Actual search terms (deterministic)

Applying `keywords_from_description(title, visual_description)`:

| Scene | visual_description (abbrev.) | **Generated query** |
|-------|------------------------------|---------------------|
| 1 | Vintage red tractor plowing... | `tractor origins vintage red plowing field italian farm` |
| 2 | 1960s Italian factory floor... | `ferruccio vision 1960s italian factory floor machinery workers` |
| 3 | Luxury sports car and tractor... | `customer dispute luxury sports car tractor parked side garage` |
| 4 | Sleek orange supercar driving... | `first lamborghini sleek orange supercar driving winding mountain road` |
| 5 | Modern Lamborghini showroom... | `brand evolution modern lamborghini showroom bright led lighting` |
| 6 | Close-up of Lamborghini logo... | `supercar legacy close lamborghini logo matte black hypercar` |

**Note:** Word order follows appearance in title+description, not importance. Generic terms (`modern`, `bright`, `side`) dilute queries.

### Step 4 — Pexels API calls (per scene)

For scene 1, query `tractor origins vintage red plowing field italian farm`:

```
GET https://api.pexels.com/v1/videos/search
  ?query=tractor+origins+vintage+red+plowing+field+italian+farm
  &per_page=6
  &orientation=portrait
```

If ≥1 video passes filters → top scored video selected → download `assets/timeline/scene_1.mp4`.

If no video → parallel:

```
GET https://api.pexels.com/v1/search?query=...&per_page=6&orientation=portrait
GET https://pixabay.com/api/?q=...&per_page=6&orientation=vertical&...
```

### Step 5 — Selection outcome

- **6 separate searches**, **6 downloads**
- Each scene gets **highest-resolution portrait** clip matching keyword bag
- **No cross-scene deduplication** — same tractor clip could appear twice if queries overlap
- Scene 4 might get a generic "orange supercar" clip not specifically Lamborghini
- Scene 1 query may return **any** red tractor, not Italian/Lamborghini-specific

---

## 10. Weaknesses

| # | Weakness | Impact |
|---|----------|--------|
| 1 | **Generic keyword queries** | Long multi-word strings confuse stock search; irrelevant results |
| 2 | **No semantic matching** | Clip selection is resolution-based, not narration-aligned |
| 3 | **Indirect script link only** | One Ollama hop (scene descriptions) with no feedback loop from search results |
| 4 | **Topic unused for search** | Same script from different topics would search identically |
| 5 | **Stop-word stripping loses context** | "before", "building" dropped; entity relationships lost |
| 6 | **First-page bias** | Only 6 results fetched; top scored among those 6, not global best |
| 7 | **No clip deduplication** | Repeated assets across scenes |
| 8 | **Weak scene-script alignment** | Scenes timed by duration math, not forced alignment to script sentences |
| 9 | **Minimum 6 scenes** | Short scripts still get 6 visuals → thin content per scene |
| 10 | **Video-first ignores narration beat** | Any portrait video matching keywords wins over a more relevant image |
| 11 | **LLM scene descriptions generic** | Prompt asks for "image prompt for AI" not "stock footage search query" |
| 12 | **No query validation** | Zero results → hard failure; no query rewrite |
| 13 | **Duration mismatch** | Downloaded clip length may not match scene; FFmpeg trims/loops without content awareness |
| 14 | **Cache keyed on query string** | Bad query cached 24h in `SearchCache` |
| 15 | **Motion effects random** | Image scenes get arbitrary ken_burns/zoom, not story-driven |

---

## 11. Scene Segmentation vs Asset Selection

| Concern | Handled by | Notes |
|---------|------------|-------|
| How many visuals | `SceneAgent` | ~1 per 5s, 6–15 scenes |
| What to show | `SceneAgent` Ollama | `visual_description` per scene |
| How long each shows | `SceneAgent` + `_normalize_durations` | Scaled to WAV length |
| What to search | `keywords_from_description` | Rule-based, not LLM |
| Which clip | `VisualTimelineAgent` | Resolution score, provider cascade |

**Gap:** Segmentation is AI-driven; search/selection is keyword + resolution — the bridge is lossy.

---

## 12. Recommendations

### Phase 2.2 — Scene Planner

| Recommendation | Rationale |
|----------------|-----------|
| Replace single Ollama blob with **structured scene planner** | Output `script_excerpt`, `search_intent`, `entities`, `shot_type` per scene |
| Align scenes to **script sentences/clauses** | Map narration text spans to visuals |
| Generate **stock-optimized search queries** (1–4 words) | LLM prompt: "Pexels search query, nouns only" |
| Variable scene count by script length | Drop 6-scene minimum for short content |
| Validate scene coverage | Ensure every script sentence maps to ≥1 scene |

### Phase 2.3 — Semantic Search

| Recommendation | Rationale |
|----------------|-----------|
| Embed `script_excerpt` + clip metadata/thumbnails | Score relevance, not just resolution |
| Use Pexels result **page 2–3** or higher `per_page` | Reduce first-page generic bias |
| Query expansion with **domain synonyms** | e.g. "tractor" → "farm equipment", "Lamborghini" → "Italian supercar" |
| Fallback query ladder | If 0 results, simplify query automatically |
| Optional: vision model on thumbnail grid | Pick clip that matches scene intent |

### Phase 2.4 — Clip Ranking

| Recommendation | Rationale |
|----------------|-----------|
| Multi-factor score: **relevance + resolution + duration fit + diversity** | Penalize clips already used |
| Prefer clips with duration ≥ scene length | Reduce loop artifacts |
| **Cross-scene deduplication** | Track Pexels video IDs |
| Log selected clip metadata per scene | Debug mismatches in `scenes/scenes.json` |
| A/B rank: Pexels order vs custom score | Measure narration-footage alignment |

---

## 13. Summary Table

| Stage | Component | Search input | AI? |
|-------|-----------|--------------|-----|
| Topic → Script | `ScriptGenerator` | Topic | Yes (Ollama) |
| Script → Scenes | `SceneAgent` | Full script | Yes (Ollama) |
| Scene → Query | `keywords_from_description` | title + visual_description | **No** |
| Query → Clips | Pexels / Pixabay APIs | Keyword string | No |
| Clips → Selection | `VideoCandidate.score()` | Resolution/portrait | No |
| Assets → Video | `VisualTimelineAgent` FFmpeg | Local files + WAV + SRT | No |

**Root cause of footage mismatch:** Stock search queries are **low-information keyword bags** derived from **generic LLM scene descriptions**, and clips are chosen for **pixel dimensions**, not **narrative relevance** to the script.

---

*End of Phase 2.1 Asset Pipeline Audit*
