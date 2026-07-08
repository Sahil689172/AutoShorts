# Pipeline Timeline Profiler (Phase 3.7A)

Lightweight wall-clock profiler that measures every major agent and phase during video generation.

---

## Architecture

```
main.py / pipeline_runner.run_job()
  reset_profiler()
  start("Entire Pipeline")
    ├── Script Generator
    ├── Narrator (Piper|Kokoro)
    ├── Caption Generator
    ├── Scene Agent
    └── VisualTimelineAgent.generate()
          ├── Object Extraction
          ├── Query Agent
          ├── Asset Search
          │     └── Provider Manager (per API search call)
          ├── Clip Ranking
          ├── Asset Download
          ├── FFmpeg Rendering
          ├── Subtitle Burn
          └── Video Export
  end("Entire Pipeline")
  summary()  → stdout
  save_json() → logs/pipeline_timeline.json
```

**Module:** `backend/services/profiler/pipeline_profiler.py`

**Global instance:**

```python
from backend.services.profiler import get_profiler, reset_profiler

profiler = reset_profiler()  # once per pipeline run
profiler.start("Script Generator")
# ...
profiler.end("Script Generator")
```

Or use the context manager:

```python
with profiler.track("Query Agent"):
    ...
```

Multiple `start`/`end` pairs for the same agent name are **aggregated** (durations summed, earliest start and latest end recorded). This supports per-scene instrumentation (e.g. Clip Ranking across N scenes).

---

## Measured agents

| Agent | Where instrumented |
|-------|-------------------|
| Script Generator | `main.py`, `pipeline_runner.py` |
| Narrator (Piper/Kokoro) | `main.py`, `pipeline_runner.py` |
| Caption Generator | `main.py`, `pipeline_runner.py` |
| Scene Agent | `main.py`, `pipeline_runner.py` |
| Object Extraction | `VisualTimelineAgent._extract_scene_objects()` |
| Query Agent | `VisualTimelineAgent._generate_search_queries()` |
| Provider Manager | `provider_manager.search()` per query |
| Asset Search | `VisualTimelineAgent._search_and_download_assets_parallel()` search phase |
| Clip Ranking | `VisualTimelineAgent._select_video_from_pool()` |
| Timeline Metadata Loading | `segment_selector.select_trim_window()` load loop |
| Timestamp Selection | `segment_selector.select_trim_window()` scoring + trim |
| Asset Download | `VisualTimelineAgent._search_and_download_assets_parallel()` download phase |
| FFmpeg Rendering | segment render + concat |
| Subtitle Burn | subtitle filter string build |
| Video Export | final FFmpeg mux to `videos/output.mp4` |
| Entire Pipeline | wraps full run |

---

## Terminal output

Printed automatically after every successful Short:

```
===================================================
           AutoShorts Pipeline Timeline
===================================================

Script Generator .............  2.43 s (4%)
Narrator (Kokoro) ............  6.81 s (11%)
...
---------------------------------------------------
TOTAL PIPELINE .............. 60.97 s
===================================================
```

Percentages are relative to **Entire Pipeline** duration. Values under 1% display as `<1%`.

---

## JSON format

**Path:** `logs/pipeline_timeline.json`

```json
[
  {
    "agent": "Narrator (Kokoro)",
    "start": 12.45,
    "end": 19.26,
    "duration": 6.81,
    "duration_ms": 6810.0,
    "percentage": 11.2
  }
]
```

| Field | Description |
|-------|-------------|
| `agent` | Display name of the measured agent |
| `start` | Seconds since pipeline origin when agent work began |
| `end` | Seconds since pipeline origin when agent work finished |
| `duration` | Wall-clock seconds (aggregated if multiple spans) |
| `duration_ms` | Same duration in milliseconds |
| `percentage` | Share of total pipeline time |

`Entire Pipeline` is included in the terminal summary but omitted from JSON (other entries already sum to ~100%).

---

## How to add timing for future agents

1. Add a constant in `pipeline_profiler.py`:

   ```python
   AGENT_MY_NEW_AGENT = "My New Agent"
   ```

2. Add it to `DISPLAY_ORDER` for summary ordering.

3. Instrument at the call site (no business logic changes):

   ```python
   from backend.services.profiler import get_profiler, AGENT_MY_NEW_AGENT

   with get_profiler().track(AGENT_MY_NEW_AGENT):
       my_new_agent.run()
   ```

4. Export the constant from `backend/services/profiler/__init__.py` if needed elsewhere.

**Rules:**

- Call `reset_profiler()` once at the start of each pipeline run (`main.py` / `pipeline_runner.run_job()`).
- Use `time.perf_counter()` only inside the profiler — do not add timers in business code.
- Prefer `track()` context managers so `end()` runs on exceptions.

---

## Performance

The profiler uses `time.perf_counter()` and in-memory dict/list operations only. No I/O during measurement. JSON is written once at the end. Overhead is well under 1% of total pipeline time.

---

## Related

- `pipeline_timing.py` — existing coarse phase timer (API/frontend); kept alongside the profiler
- [Timestamp Selection](timestamp_selection.md)
