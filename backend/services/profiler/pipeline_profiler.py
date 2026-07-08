"""Global pipeline timeline profiler — lightweight wall-clock instrumentation."""

from __future__ import annotations

import json
import logging
import os
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

logger = logging.getLogger(__name__)

TIMELINE_JSON_PATH = Path("logs/pipeline_timeline.json")

# Canonical agent labels (display order for summary).
AGENT_SCRIPT_GENERATOR = "Script Generator"
AGENT_NARRATOR = "Narrator"
AGENT_CAPTION_GENERATOR = "Caption Generator"
AGENT_SCENE_AGENT = "Scene Agent"
AGENT_OBJECT_EXTRACTION = "Object Extraction"
AGENT_QUERY_AGENT = "Query Agent"
AGENT_PROVIDER_MANAGER = "Provider Manager"
AGENT_ASSET_SEARCH = "Asset Search"
AGENT_CLIP_RANKING = "Clip Ranking"
AGENT_TIMELINE_METADATA = "Timeline Metadata Loading"
AGENT_TIMESTAMP_SELECTION = "Timestamp Selection"
AGENT_ASSET_DOWNLOAD = "Asset Download"
AGENT_FFMPEG_RENDERING = "FFmpeg Rendering"
AGENT_SUBTITLE_BURN = "Subtitle Burn"
AGENT_VIDEO_EXPORT = "Video Export"
AGENT_ENTIRE_PIPELINE = "Entire Pipeline"

DISPLAY_ORDER: tuple[str, ...] = (
    AGENT_SCRIPT_GENERATOR,
    AGENT_NARRATOR,
    AGENT_CAPTION_GENERATOR,
    AGENT_SCENE_AGENT,
    AGENT_OBJECT_EXTRACTION,
    AGENT_QUERY_AGENT,
    AGENT_PROVIDER_MANAGER,
    AGENT_ASSET_SEARCH,
    AGENT_CLIP_RANKING,
    AGENT_TIMELINE_METADATA,
    AGENT_TIMESTAMP_SELECTION,
    AGENT_ASSET_DOWNLOAD,
    AGENT_FFMPEG_RENDERING,
    AGENT_SUBTITLE_BURN,
    AGENT_VIDEO_EXPORT,
    AGENT_ENTIRE_PIPELINE,
)


def narrator_agent_name() -> str:
    """Resolve narrator label for profiler (e.g. Narrator (Kokoro))."""
    provider = os.environ.get("NARRATOR_PROVIDER", "piper").strip().lower()
    if provider == "kokoro":
        return "Narrator (Kokoro)"
    if provider == "piper":
        return "Narrator (Piper)"
    return f"Narrator ({provider.title()})"


@dataclass
class TimingRecord:
    """Aggregated timing for one agent (may span multiple start/end pairs)."""

    agent: str
    start: float  # seconds since pipeline origin
    end: float
    duration: float  # seconds
    duration_ms: float
    percentage: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent": self.agent,
            "start": round(self.start, 2),
            "end": round(self.end, 2),
            "duration": round(self.duration, 2),
            "duration_ms": round(self.duration_ms, 1),
            "percentage": round(self.percentage, 1),
        }


@dataclass
class _OpenSpan:
    wall_start: float
    origin_start: float


@dataclass
class PipelineProfiler:
    """Wall-clock profiler for AutoShorts pipeline agents."""

    _origin: float = field(default_factory=time.perf_counter)
    _open: dict[str, _OpenSpan] = field(default_factory=dict)
    _spans: dict[str, list[tuple[float, float, float]]] = field(default_factory=dict)
    # agent -> list of (origin_start, origin_end, duration_sec)

    def _origin_now(self) -> float:
        return time.perf_counter() - self._origin

    def start(self, name: str) -> None:
        if name in self._open:
            logger.debug("Profiler: nested start for %r ignored", name)
            return
        now = time.perf_counter()
        self._open[name] = _OpenSpan(wall_start=now, origin_start=self._origin_now())

    def end(self, name: str) -> None:
        span = self._open.pop(name, None)
        if span is None:
            logger.debug("Profiler: end without start for %r", name)
            return
        duration = time.perf_counter() - span.wall_start
        origin_end = self._origin_now()
        self._spans.setdefault(name, []).append(
            (span.origin_start, origin_end, duration)
        )

    @contextmanager
    def track(self, name: str) -> Iterator[None]:
        self.start(name)
        try:
            yield
        finally:
            self.end(name)

    def _aggregate(self) -> list[TimingRecord]:
        records: list[TimingRecord] = []
        for agent, spans in self._spans.items():
            if not spans:
                continue
            start = min(s[0] for s in spans)
            end = max(s[1] for s in spans)
            duration = sum(s[2] for s in spans)
            records.append(
                TimingRecord(
                    agent=agent,
                    start=start,
                    end=end,
                    duration=duration,
                    duration_ms=duration * 1000.0,
                )
            )
        return records

    def _total_seconds(self, records: list[TimingRecord]) -> float:
        entire = next((r for r in records if r.agent == AGENT_ENTIRE_PIPELINE), None)
        if entire and entire.duration > 0:
            return entire.duration
        return sum(r.duration for r in records if r.agent != AGENT_ENTIRE_PIPELINE)

    def summary(self) -> str:
        """Build and print the formatted pipeline timeline."""
        records = self._ordered_records()
        total = self._total_seconds(records)
        for record in records:
            if total > 0 and record.agent != AGENT_ENTIRE_PIPELINE:
                record.percentage = (record.duration / total) * 100.0
            elif record.agent == AGENT_ENTIRE_PIPELINE:
                record.percentage = 100.0

        lines = [
            "",
            "=" * 51,
            "           AutoShorts Pipeline Timeline",
            "=" * 51,
            "",
        ]
        label_width = 28
        for record in records:
            if record.agent == AGENT_ENTIRE_PIPELINE:
                lines.append("-" * 51)
            dots = "." * max(1, label_width - len(record.agent))
            pct = self._format_percentage(record.percentage, record.agent)
            lines.append(
                f"{record.agent} {dots} {record.duration:>5.2f} s ({pct})"
            )
        lines.append("")
        lines.append(f"TOTAL PIPELINE {'.' * (label_width - 14)} {total:>5.2f} s")
        lines.append("=" * 51)
        lines.append("")
        block = "\n".join(lines)
        print(block, flush=True)
        logger.info("Pipeline timeline profiler summary (%d agents, %.2fs)", len(records), total)
        return block

    def _ordered_records(self) -> list[TimingRecord]:
        aggregated = {r.agent: r for r in self._aggregate()}
        ordered: list[TimingRecord] = []
        seen: set[str] = set()
        for name in DISPLAY_ORDER:
            if name in aggregated:
                ordered.append(aggregated[name])
                seen.add(name)
        for name, record in aggregated.items():
            if name not in seen:
                ordered.append(record)
        return ordered

    @staticmethod
    def _format_percentage(pct: float, agent: str) -> str:
        if agent == AGENT_ENTIRE_PIPELINE:
            return "100%"
        if pct < 1.0:
            return "<1%"
        return f"{pct:.0f}%"

    def to_json_list(self) -> list[dict[str, Any]]:
        records = self._ordered_records()
        total = self._total_seconds(records)
        for record in records:
            if total > 0 and record.agent != AGENT_ENTIRE_PIPELINE:
                record.percentage = (record.duration / total) * 100.0
        return [r.to_dict() for r in records if r.agent != AGENT_ENTIRE_PIPELINE]

    def save_json(self, path: Path = TIMELINE_JSON_PATH) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = self.to_json_list()
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        logger.info("Pipeline timeline saved: %s", path)
        return path


_active_profiler: PipelineProfiler | None = None


def get_profiler() -> PipelineProfiler:
    """Return the active global profiler (creates one if missing)."""
    global _active_profiler
    if _active_profiler is None:
        _active_profiler = PipelineProfiler()
    return _active_profiler


def reset_profiler() -> PipelineProfiler:
    """Reset and return a fresh global profiler for a new pipeline run."""
    global _active_profiler
    _active_profiler = PipelineProfiler()
    return _active_profiler
