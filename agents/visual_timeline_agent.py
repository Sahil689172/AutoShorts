"""Video-first visual timeline: Pexels videos → Pexels images → Pixabay → single output."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import random
import re
import shutil
import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Literal

import requests

from agents.topic_cache import TopicAssetCache

from agents.subtitle_config import build_subtitle_force_style
from agents.timeline_video_builder import (
    FFMPEG_TIMEOUT_BUFFER,
    MOTION_EFFECTS,
    VIDEO_FPS,
    VIDEO_HEIGHT,
    VIDEO_WIDTH,
    build_motion_filter,
    escape_subtitles_path,
    probe_duration,
    resolve_ffmpeg_tool,
)
from agents.candidate_pool import (
    RESULTS_PER_QUERY,
    PoolStats,
    merge_query_results,
)
from agents.query_agent import QueryAgent
from agents.session_asset_registry import SessionAssetRegistry, video_hash
from backend.services.assets.asset_provider_manager import AssetProviderManager
from backend.services.assets.providers.asset_provider import ProviderAsset
from backend.services.assets.ranking import ClipRanker, RankingResult
from backend.services.clip_intelligence.metadata_store import MetadataStore
from backend.services.clip_intelligence.segment_selector import (
    TrimSelection,
    select_trim_window,
    tokenize,
)
from backend.services.profiler import (
    AGENT_ASSET_DOWNLOAD,
    AGENT_ASSET_SEARCH,
    AGENT_CLIP_RANKING,
    AGENT_FFMPEG_RENDERING,
    AGENT_OBJECT_EXTRACTION,
    AGENT_PROVIDER_MANAGER,
    AGENT_QUERY_AGENT,
    AGENT_SUBTITLE_BURN,
    AGENT_VIDEO_EXPORT,
    get_profiler,
)
from backend.services.scene_understanding import (
    ExtractedObjects,
    ObjectExtractor,
    ObjectExtractionError,
    map_narration_to_scenes,
)
from agents.visual_asset_agent import (
    APIKeyMissingError,
    CACHE_DIR,
    CACHE_TTL_SECONDS,
    MIN_IMAGE_HEIGHT,
    MIN_IMAGE_WIDTH,
    REQUEST_TIMEOUT,
    SearchCache,
    PexelsClient,
    PixabayClient,
)

logger = logging.getLogger(__name__)

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

SCENES_PATH = Path("scenes/scenes.json")
SCRIPT_PATH = Path("scripts/script.txt")
TIMELINE_ASSETS_DIR = Path("assets/timeline")
AUDIO_PATH = Path("audio/output.wav")
CAPTIONS_PATH = Path("captions/output.srt")
OUTPUT_PATH = Path("videos/output.mp4")
VIDEOS_DIR = Path("videos")

MIN_SEGMENT_SECONDS = 2.0
PROGRESS_STEPS = 8
DEFAULT_FFMPEG = "ffmpeg"
DEFAULT_FFPROBE = "ffprobe"

AssetKind = Literal["video", "image"]
SourceKind = Literal["pexels_video", "pexels_image", "pixabay_image"]


class VisualTimelineAgentError(Exception):
    """Base error for visual timeline generation."""


class ScenesNotFoundError(VisualTimelineAgentError):
    """scenes/scenes.json is missing or invalid."""


class NarrationNotFoundError(VisualTimelineAgentError):
    """Narration audio is missing."""


class CaptionsNotFoundError(VisualTimelineAgentError):
    """Captions file is missing."""


class FFmpegNotFoundError(VisualTimelineAgentError):
    """FFmpeg or ffprobe is not available."""


class TimelineAssetError(VisualTimelineAgentError):
    """Failed to acquire or render a timeline asset."""


class TimelineRenderError(VisualTimelineAgentError):
    """FFmpeg failed during timeline rendering."""


# Unified provider asset type (scoring + candidate pool compatible).
VideoCandidate = ProviderAsset


@dataclass
class SceneRecord:
    scene_number: int
    title: str
    visual_description: str
    duration_seconds: float
    queries: list[str] | None = None
    query: str = ""
    asset_kind: AssetKind | None = None
    source: SourceKind | None = None
    asset_path: Path | None = None
    motion_effect: str | None = None
    pending_url: str | None = None
    pending_ext: str | None = None
    selected_asset_url: str = ""
    selected_clip_id: str = ""
    selection_reason: str = ""
    previously_used: bool = False
    narration_text: str = ""
    extracted_objects: ExtractedObjects | None = None

    def __post_init__(self) -> None:
        if self.queries is None:
            self.queries = []


@dataclass
class TimelineBuildResult:
    output_path: Path
    scene_count: int
    video_scenes: int
    image_scenes: int
    narration_seconds: float
    final_seconds: float


class AssetFileCache:
    """Persist downloaded scene assets to avoid redundant downloads."""

    def __init__(self, assets_dir: Path = TIMELINE_ASSETS_DIR) -> None:
        self.assets_dir = assets_dir
        self.meta_path = assets_dir / "manifest.json"

    def _load_manifest(self) -> dict[str, Any]:
        if not self.meta_path.is_file():
            return {}
        try:
            data = json.loads(self.meta_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _save_manifest(self, manifest: dict[str, Any]) -> None:
        self.assets_dir.mkdir(parents=True, exist_ok=True)
        self.meta_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    def get_cached_path(
        self,
        scene_number: int,
        url: str,
        extension: str,
    ) -> Path | None:
        digest = hashlib.sha256(url.encode()).hexdigest()[:16]
        manifest = self._load_manifest()
        key = str(scene_number)
        entry = manifest.get(key)
        if not isinstance(entry, dict):
            return None
        if entry.get("url_hash") != digest:
            return None
        path = self.assets_dir / f"scene_{scene_number}{extension}"
        if path.is_file() and path.stat().st_size > 10_000:
            logger.debug("Asset cache hit for scene %d", scene_number)
            return path
        return None

    def record(self, scene_number: int, url: str, path: Path, kind: AssetKind, source: str) -> None:
        digest = hashlib.sha256(url.encode()).hexdigest()[:16]
        manifest = self._load_manifest()
        manifest[str(scene_number)] = {
            "url_hash": digest,
            "path": path.name,
            "kind": kind,
            "source": source,
            "cached_at": time.time(),
        }
        self._save_manifest(manifest)


class VisualTimelineAgent:
    """
    Video-first pipeline: search stock video → image fallbacks, build one timeline,
    render a single videos/output.mp4 with narration and captions.
    """

    def __init__(
        self,
        scenes_path: Path | str = SCENES_PATH,
        assets_dir: Path | str = TIMELINE_ASSETS_DIR,
        audio_path: Path | str = AUDIO_PATH,
        captions_path: Path | str = CAPTIONS_PATH,
        output_path: Path | str = OUTPUT_PATH,
        cache_dir: Path | str = CACHE_DIR,
        ffmpeg: str | None = None,
        ffprobe: str | None = None,
        provider_manager: AssetProviderManager | None = None,
        pexels_images: PexelsClient | None = None,
        pixabay: PixabayClient | None = None,
        topic: str | None = None,
        timer: Any | None = None,
        on_timing_sync: Any | None = None,
        max_search_workers: int | None = None,
        max_download_workers: int | None = None,
        query_agent: QueryAgent | None = None,
        session_registry: SessionAssetRegistry | None = None,
        clip_ranker: ClipRanker | None = None,
        object_extractor: ObjectExtractor | None = None,
    ) -> None:
        self.scenes_path = Path(scenes_path)
        self.assets_dir = Path(assets_dir)
        self.audio_path = Path(audio_path)
        self.captions_path = Path(captions_path)
        self.output_path = Path(output_path)
        self.ffmpeg = resolve_ffmpeg_tool(ffmpeg or DEFAULT_FFMPEG, "FFMPEG_EXECUTABLE")
        self.ffprobe = resolve_ffmpeg_tool(ffprobe or DEFAULT_FFPROBE, "FFPROBE_EXECUTABLE")
        self.search_cache = SearchCache(Path(cache_dir), CACHE_TTL_SECONDS)
        self.file_cache = AssetFileCache(self.assets_dir)
        self.provider_manager = provider_manager or AssetProviderManager(
            search_cache=self.search_cache
        )
        self.pexels_images = pexels_images or PexelsClient(cache=self.search_cache)
        self.pixabay = pixabay or PixabayClient(cache=self.search_cache)
        self.topic = (topic or "").strip()
        self.topic_cache = TopicAssetCache(self.topic) if self.topic else None
        self._timer = timer
        self._on_timing_sync = on_timing_sync
        default_search = int(os.environ.get("ASSET_SEARCH_WORKERS", "12"))
        default_download = int(os.environ.get("ASSET_DOWNLOAD_WORKERS", "10"))
        self.max_search_workers = max(1, max_search_workers or default_search)
        self.max_download_workers = max(1, max_download_workers or default_download)
        self.query_agent = query_agent or QueryAgent()
        self.session_registry = session_registry or SessionAssetRegistry()
        self.clip_ranker = clip_ranker or ClipRanker()
        self.object_extractor = object_extractor or ObjectExtractor()
        self.timeline_metadata_store = MetadataStore()
        # Per-scene diagnostics for asset search failures/summaries (Phase 3.7F).
        self._scene_search_diagnostics: dict[int, dict[str, Any]] = {}
        self._scene_url_queries: dict[int, dict[str, str]] = {}
        self._scenes: list[SceneRecord] = []
        self._narration_seconds = 0.0
        self._temp_dir: Path | None = None
        self._asset_search_seconds = 0.0
        self._video_render_seconds = 0.0

    def generate(self) -> TimelineBuildResult:
        """Build one final Short from scenes.json with video-first visuals."""
        if not self._has_any_api_key():
            raise APIKeyMissingError(
                "No API keys configured. Set PEXELS_API_KEY and/or PIXABAY_API_KEY in .env"
            )

        VIDEOS_DIR.mkdir(parents=True, exist_ok=True)
        self.assets_dir.mkdir(parents=True, exist_ok=True)
        self.search_cache.cache_dir.mkdir(parents=True, exist_ok=True)
        self.session_registry.reset_for_session()
        self._verify_ffmpeg()

        self._print_progress(1, "Reading scenes...")
        self._read_scenes()
        self._narration_seconds = self._read_narration_duration()
        self._normalize_durations()

        asset_started = time.perf_counter()
        self._print_progress(2, "Extracting objects and search queries...")
        profiler = get_profiler()
        with profiler.track(AGENT_OBJECT_EXTRACTION):
            self._extract_scene_objects()
        with profiler.track(AGENT_QUERY_AGENT):
            self._generate_search_queries()
        self._print_progress(3, "Resolving scene assets (parallel)...")
        self._restore_from_topic_cache()
        self._search_and_download_assets_parallel()
        self._asset_search_seconds = time.perf_counter() - asset_started
        logger.info("Asset search + download: %.2f sec", self._asset_search_seconds)
        self._publish_timing(asset=True)

        self._print_progress(4, "Building timeline...")
        missing = [s for s in self._scenes if s.asset_path is None]
        if missing:
            numbers = ", ".join(str(s.scene_number) for s in missing)
            raise TimelineAssetError(
                f"No visual asset found for scene(s): {numbers}. "
                "Check API keys and scene descriptions."
            )
        self._assign_motion_effects()

        self._temp_dir = Path(tempfile.mkdtemp(prefix="yt_visual_timeline_"))
        try:
            video_started = time.perf_counter()
            self._print_progress(5, "Applying motion...")
            profiler = get_profiler()
            profiler.start(AGENT_FFMPEG_RENDERING)
            segment_paths = self._render_timeline_segments()
            visual_path = self._concat_segments(segment_paths)
            profiler.end(AGENT_FFMPEG_RENDERING)

            self._print_progress(6, "Adding narration...")
            self._print_progress(7, "Adding captions...")
            self._finalize_with_audio_and_subtitles(visual_path)
            self._video_render_seconds = time.perf_counter() - video_started
            logger.info("Video generation: %.2f sec", self._video_render_seconds)
            self._publish_timing(video=True)

            self._print_progress(8, "Completed")
            self._verify_output()
            self._persist_topic_cache()
            self._record_timing_splits()
            final_seconds = probe_duration(self.output_path, self.ffprobe)
            result = TimelineBuildResult(
                output_path=self.output_path.resolve(),
                scene_count=len(self._scenes),
                video_scenes=sum(1 for s in self._scenes if s.asset_kind == "video"),
                image_scenes=sum(1 for s in self._scenes if s.asset_kind == "image"),
                narration_seconds=self._narration_seconds,
                final_seconds=final_seconds,
            )
            self._print_summary(result)
            return result
        finally:
            if self._temp_dir and self._temp_dir.exists():
                shutil.rmtree(self._temp_dir, ignore_errors=True)
                logger.debug("Removed temp visual timeline directory")

    def _has_any_api_key(self) -> bool:
        return bool(
            self.provider_manager.is_configured()
            or self.pexels_images.api_key
            or self.pixabay.api_key
        )

    def _print_progress(self, step: int, message: str) -> None:
        print(f"[{step}/{PROGRESS_STEPS}] {message}", flush=True)
        logger.info("%s", message)

    def _verify_ffmpeg(self) -> None:
        for tool in (self.ffmpeg, self.ffprobe):
            if shutil.which(tool) is None and not Path(tool).is_file():
                raise FFmpegNotFoundError(f"{tool} not found on PATH.")
        logger.info("FFmpeg: %s", self.ffmpeg)
        logger.info("FFprobe: %s", self.ffprobe)

    def _read_scenes(self) -> None:
        if not self.scenes_path.is_file():
            raise ScenesNotFoundError(
                f"Scenes file not found: {self.scenes_path}. Run Phase 4.5A first."
            )
        try:
            data = json.loads(self.scenes_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ScenesNotFoundError(f"Cannot read scenes file: {exc}") from exc

        if isinstance(data, dict) and "scenes" in data:
            data = data["scenes"]
        if not isinstance(data, list) or not data:
            raise ScenesNotFoundError("scenes.json must contain a non-empty scene list.")

        self._scenes = []
        for item in data:
            if not isinstance(item, dict):
                continue
            try:
                scene_number = int(item["scene_number"])
            except (KeyError, TypeError, ValueError):
                continue
            title = str(item.get("title") or f"Scene {scene_number}").strip()
            visual_description = str(item.get("visual_description") or "").strip()
            if not visual_description:
                continue
            try:
                duration = float(item.get("duration_seconds") or 5)
            except (TypeError, ValueError):
                duration = 5.0
            duration = max(MIN_SEGMENT_SECONDS, duration)
            self._scenes.append(
                SceneRecord(
                    scene_number=scene_number,
                    title=title,
                    visual_description=visual_description,
                    duration_seconds=duration,
                )
            )

        self._scenes.sort(key=lambda s: s.scene_number)
        if not self._scenes:
            raise ScenesNotFoundError("No valid scenes found in scenes.json.")

        logger.info("Loaded %d scenes from %s", len(self._scenes), self.scenes_path)
        for scene in self._scenes:
            print(
                f"  Scene {scene.scene_number}: {scene.title} "
                f"({scene.duration_seconds:.1f}s)",
                flush=True,
            )

    def _read_narration_duration(self) -> float:
        if not self.audio_path.is_file():
            raise NarrationNotFoundError(
                f"Narration not found: {self.audio_path}. Run Phase 2 first."
            )
        duration = probe_duration(self.audio_path, self.ffprobe)
        logger.info("Narration duration: %.2f seconds", duration)
        print(f"  Narration length: {duration:.1f}s", flush=True)
        return duration

    def _normalize_durations(self) -> None:
        """Scale per-scene durations to match narration length."""
        total = sum(s.duration_seconds for s in self._scenes)
        if total <= 0:
            per_scene = self._narration_seconds / len(self._scenes)
            for scene in self._scenes:
                scene.duration_seconds = max(MIN_SEGMENT_SECONDS, per_scene)
            return

        ratio = self._narration_seconds / total
        for scene in self._scenes:
            scene.duration_seconds = max(
                MIN_SEGMENT_SECONDS,
                scene.duration_seconds * ratio,
            )

        adjusted = sum(s.duration_seconds for s in self._scenes)
        drift = self._narration_seconds - adjusted
        if self._scenes and abs(drift) > 0.05:
            self._scenes[-1].duration_seconds = max(
                MIN_SEGMENT_SECONDS,
                self._scenes[-1].duration_seconds + drift,
            )

        logger.info(
            "Timeline durations normalized to %.2fs across %d scenes",
            self._narration_seconds,
            len(self._scenes),
        )
        per_avg = self._narration_seconds / len(self._scenes)
        print(
            f"  {len(self._scenes)} scenes × ~{per_avg:.1f}s ≈ {self._narration_seconds:.1f}s",
            flush=True,
        )

    def _load_narration_script(self) -> str:
        if not SCRIPT_PATH.is_file():
            logger.warning("Narration script not found at %s", SCRIPT_PATH)
            return ""
        try:
            return SCRIPT_PATH.read_text(encoding="utf-8").strip()
        except OSError as exc:
            logger.warning("Cannot read narration script: %s", exc)
            return ""

    def _extract_scene_objects(self) -> None:
        """Identify visual objects per scene before query generation."""
        script = self._load_narration_script()
        narration_map = map_narration_to_scenes(script, self._scenes) if script else {}

        for scene in self._scenes:
            if scene.asset_path or scene.extracted_objects:
                continue
            scene.narration_text = narration_map.get(scene.scene_number, script)
            try:
                scene.extracted_objects = self.object_extractor.extract(
                    scene.title,
                    scene.visual_description,
                    scene.narration_text,
                )
            except ObjectExtractionError as exc:
                logger.warning(
                    "Scene %d object extraction failed: %s",
                    scene.scene_number,
                    exc,
                )
                scene.extracted_objects = ExtractedObjects(
                    primary_objects=[scene.title] if scene.title else [],
                )

    def _generate_search_queries(self) -> None:
        """Build semantic Pexels queries using extracted objects via QueryAgent."""
        for scene in self._scenes:
            if scene.asset_path or scene.queries:
                continue
            scene.queries = self.query_agent.generate_queries(
                scene.title,
                scene.visual_description,
                extracted_objects=scene.extracted_objects,
                narration_text=scene.narration_text,
            )
            scene.query = scene.queries[0] if scene.queries else ""
            self._log_object_query_debug(scene)

    def _restore_from_topic_cache(self) -> None:
        if not self.topic_cache or not self.topic_cache.is_available():
            return
        restored = 0
        for scene in self._scenes:
            if scene.asset_path:
                continue
            candidates = scene.queries or ([scene.query] if scene.query else [])
            for query in candidates:
                path, kind, source = self.topic_cache.try_restore_scene(
                    scene.scene_number,
                    query,
                )
                if path:
                    scene.asset_path = path
                    scene.asset_kind = kind or "video"
                    scene.source = source
                    scene.query = query
                    restored += 1
                    if scene.asset_kind == "video":
                        self._register_restored_video(scene, path, source)
                    break
        if restored:
            print(f"  Topic cache: restored {restored} scene asset(s)", flush=True)

    def _search_and_download_assets_parallel(self) -> None:
        needs_search = [s for s in self._scenes if not s.asset_path]
        pools: dict[int, list[VideoCandidate]] = {}
        profiler = get_profiler()

        if needs_search:
            profiler.start(AGENT_ASSET_SEARCH)
            try:
                workers = min(self.max_search_workers, len(needs_search))
                with ThreadPoolExecutor(max_workers=workers) as executor:
                    futures = {
                        executor.submit(self._build_video_candidate_pool, scene): scene
                        for scene in needs_search
                    }
                    for future in as_completed(futures):
                        scene = futures[future]
                        try:
                            pools[scene.scene_number] = future.result()
                        except Exception as exc:
                            logger.error(
                                "Scene %d candidate pool build failed: %s",
                                scene.scene_number,
                                exc,
                            )
                            pools[scene.scene_number] = []

                for scene in sorted(needs_search, key=lambda s: s.scene_number):
                    if scene.asset_path or scene.pending_url:
                        continue
                    pool = pools.get(scene.scene_number, [])
                    if pool:
                        self._select_video_from_pool(scene, pool)
                    if not scene.pending_url:
                        self._resolve_image_fallback(scene)
                    if not scene.pending_url and not scene.asset_path:
                        # No video selection and no image fallback → print diagnostics.
                        self._print_scene_search_diagnostics(scene)
            finally:
                profiler.end(AGENT_ASSET_SEARCH)

        to_download = [
            s
            for s in self._scenes
            if s.pending_url and s.pending_ext and s.asset_kind and not s.asset_path
        ]
        if to_download:
            profiler.start(AGENT_ASSET_DOWNLOAD)
            try:
                workers = min(self.max_download_workers, len(to_download))
                with ThreadPoolExecutor(max_workers=workers) as executor:
                    futures = {
                        executor.submit(self._download_scene_asset, scene): scene
                        for scene in to_download
                    }
                    for future in as_completed(futures):
                        try:
                            future.result()
                        except Exception as exc:
                            logger.error("Parallel download error: %s", exc)
            finally:
                profiler.end(AGENT_ASSET_DOWNLOAD)

    def _build_video_candidate_pool(self, scene: SceneRecord) -> list[VideoCandidate]:
        """Search every query and merge into one deduplicated candidate pool."""
        queries = scene.queries or ([scene.query] if scene.query else [])
        if not queries or not self.provider_manager.is_configured():
            self._scene_search_diagnostics[scene.scene_number] = {
                "title": scene.title,
                "objects": (scene.extracted_objects.summary_labels() if scene.extracted_objects else []),
                "queries": queries,
                "results_per_query": {q: 0 for q in queries},
                "raw_total": 0,
                "pool_size": 0,
                "duplicate_count": 0,
                "failure_reason": "Provider manager not configured or no queries",
            }
            return []

        query_results: dict[str, list[VideoCandidate]] = {}
        url_to_query: dict[str, str] = {}
        workers = min(len(queries), 5)

        def search_query(query: str) -> tuple[str, list[VideoCandidate]]:
            profiler = get_profiler()
            try:
                profiler.start(AGENT_PROVIDER_MANAGER)
                clips = self.provider_manager.search(query, per_page=RESULTS_PER_QUERY)
                profiler.end(AGENT_PROVIDER_MANAGER)
                tagged = [
                    replace(c, source_query=query)
                    for c in clips[:RESULTS_PER_QUERY]
                ]
                return query, tagged
            except Exception as exc:
                get_profiler().end(AGENT_PROVIDER_MANAGER)
                logger.warning(
                    "Scene %d provider search failed for %r: %s",
                    scene.scene_number,
                    query,
                    exc,
                )
                return query, []

        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(search_query, q): q for q in queries}
            for future in as_completed(futures):
                query, clips = future.result()
                query_results[query] = clips

        for query in queries:
            for clip in query_results.get(query, []):
                if clip.url not in url_to_query:
                    url_to_query[clip.url] = query

        pool, stats = merge_query_results(query_results)
        self._scene_url_queries[scene.scene_number] = url_to_query
        self._log_candidate_pool(scene, stats)
        self._scene_search_diagnostics[scene.scene_number] = {
            "title": scene.title,
            "objects": (scene.extracted_objects.summary_labels() if scene.extracted_objects else []),
            "queries": queries,
            "results_per_query": dict(stats.results_per_query),
            "raw_total": stats.raw_total,
            "pool_size": stats.pool_size,
            "duplicate_count": stats.duplicate_count,
        }
        return pool

    def _select_video_from_pool(
        self,
        scene: SceneRecord,
        pool: list[VideoCandidate],
    ) -> None:
        url_to_query = self._scene_url_queries.get(scene.scene_number, {})
        queries = scene.queries or ([scene.query] if scene.query else [])
        profiler = get_profiler()
        profiler.start(AGENT_CLIP_RANKING)
        ranking = self.clip_ranker.rank(
            title=scene.title,
            visual_description=scene.visual_description,
            queries=queries,
            pool=pool,
            registry=self.session_registry,
            source_queries=url_to_query,
            scene_number=scene.scene_number,
        )
        profiler.end(AGENT_CLIP_RANKING)
        if ranking is None:
            self._print_scene_search_diagnostics(scene, failure_reason="ClipRanker returned no winner")
            return

        winner = ranking.winner
        clip = winner.candidate
        clip_id = clip.clip_id or video_hash(clip.url)
        scene.query = winner.source_query or clip.source_query or scene.query
        scene.asset_kind = "video"
        scene.source = "pexels_video"
        scene.pending_url = clip.url
        scene.pending_ext = ".mp4"
        scene.selected_asset_url = clip.url
        scene.selected_clip_id = clip_id
        scene.selection_reason = ranking.reason
        scene.previously_used = winner.previously_used

        self.session_registry.register(
            clip_id,
            "pexels_video",
            clip.url,
            scene.scene_number,
        )
        self._log_scene_selection(scene, ranking)
        self._print_scene_search_diagnostics(scene, ranking=ranking)

    def _print_scene_search_diagnostics(
        self,
        scene: SceneRecord,
        *,
        ranking: RankingResult | None = None,
        failure_reason: str | None = None,
    ) -> None:
        """
        Print a high-signal, per-scene diagnostics block for asset search.

        Does not change any search logic; intended to make failures debuggable without reading code.
        """
        diag = self._scene_search_diagnostics.get(scene.scene_number, {})
        title = diag.get("title") or scene.title
        objects = diag.get("objects") or (scene.extracted_objects.summary_labels() if scene.extracted_objects else [])
        queries = diag.get("queries") or (scene.queries or ([scene.query] if scene.query else []))
        results_per_query: dict[str, int] = dict(diag.get("results_per_query") or {})
        raw_total = int(diag.get("raw_total") or sum(results_per_query.values()) or 0)
        pool_size = int(diag.get("pool_size") or 0)
        dupes = int(diag.get("duplicate_count") or 0)
        after_dedup = pool_size
        after_ranking = len(ranking.ranked) if ranking else 0

        if failure_reason is None:
            if diag.get("failure_reason"):
                failure_reason = str(diag["failure_reason"])
            elif not queries:
                failure_reason = "No queries generated"
            elif raw_total == 0:
                failure_reason = "No API results"
            elif after_dedup == 0 and raw_total > 0:
                failure_reason = "All results removed by deduplication"
            elif ranking is None:
                failure_reason = "Filtered by ranking or no eligible candidates"

        print("\n" + "=" * 49, flush=True)
        print(f"Scene {scene.scene_number}", flush=True)
        print("", flush=True)
        print("Title:", flush=True)
        print(f"{title}", flush=True)
        print("", flush=True)
        print("Objects:", flush=True)
        if objects:
            for obj in objects:
                print(f"{obj}", flush=True)
        else:
            print("(none)", flush=True)
        print("", flush=True)
        print("Generated Queries:", flush=True)
        if not queries:
            print("(none)", flush=True)
        else:
            for i, q in enumerate(queries, start=1):
                results = results_per_query.get(q, 0)
                print(f"{i}.", flush=True)
                print(f"{q}", flush=True)
                print("", flush=True)
                print("Results:", flush=True)
                print(f"{results}", flush=True)
                print("", flush=True)

        print(f"Candidate Pool: {raw_total}", flush=True)
        print(f"After Dedup: {after_dedup} (removed {dupes})", flush=True)
        if ranking is not None:
            print(f"After Ranking: {after_ranking}", flush=True)
            print("", flush=True)
            print("Winning Clip:", flush=True)
            print(f"{ranking.winner.clip_label}", flush=True)
            print("", flush=True)
            print("Reason:", flush=True)
            print(f"{ranking.reason}", flush=True)
        else:
            print(f"After Ranking: 0", flush=True)
            print("", flush=True)
            print("Failure reason:", flush=True)
            print(f"{failure_reason or 'Unknown'}", flush=True)
        print("=" * 49, flush=True)

    def _resolve_image_fallback(self, scene: SceneRecord) -> None:
        """Image/Pixabay fallback when no suitable video candidate is selected."""
        queries = scene.queries or ([scene.query] if scene.query else [])
        if not queries:
            return

        def pexels_image_for_query(query: str):
            if not self.pexels_images.api_key:
                return None, None
            candidates = self.pexels_images.search(query, per_page=6)
            if candidates:
                return query, candidates[0]
            return None, None

        def pixabay_for_query(query: str):
            if not self.pixabay.api_key:
                return None, None
            candidates = self.pixabay.search(query, per_page=6)
            if candidates:
                return query, candidates[0]
            return None, None

        for query in queries:
            image_best = pixabay_best = None
            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = {}
                if self.pexels_images.api_key:
                    futures[executor.submit(pexels_image_for_query, query)] = "pexels_image"
                if self.pixabay.api_key:
                    futures[executor.submit(pixabay_for_query, query)] = "pixabay"
                for future in as_completed(futures):
                    source = futures[future]
                    try:
                        hit_query, hit = future.result()
                    except Exception as exc:
                        logger.warning(
                            "Scene %d %s search failed for %r: %s",
                            scene.scene_number,
                            source,
                            query,
                            exc,
                        )
                        continue
                    if hit is None:
                        continue
                    if source == "pexels_image":
                        image_best = (hit_query, hit)
                    else:
                        pixabay_best = (hit_query, hit)

            if image_best:
                hit_query, hit = image_best
                scene.query = hit_query
                scene.asset_kind = "image"
                scene.source = "pexels_image"
                scene.pending_url = hit.url
                scene.pending_ext = ".jpg"
                scene.selected_asset_url = hit.url
                scene.selected_clip_id = video_hash(hit.url)
                scene.selection_reason = f"Video pool empty; Pexels image fallback for {hit_query!r}"
                scene.previously_used = False
                self._log_image_selection(scene, hit_query, hit.url, "pexels_image")
                return

            if pixabay_best:
                hit_query, hit = pixabay_best
                scene.query = hit_query
                scene.asset_kind = "image"
                scene.source = "pixabay_image"
                scene.pending_url = hit.url
                scene.pending_ext = ".jpg"
                scene.selected_asset_url = hit.url
                scene.selected_clip_id = video_hash(hit.url)
                scene.selection_reason = f"Video pool empty; Pixabay image fallback for {hit_query!r}"
                scene.previously_used = False
                self._log_image_selection(scene, hit_query, hit.url, "pixabay_image")
                return

    def _register_restored_video(
        self,
        scene: SceneRecord,
        path: Path,
        source: str,
    ) -> None:
        clip_id = scene.selected_clip_id or f"cache-{scene.scene_number}"
        url = scene.selected_asset_url or str(path.resolve())
        scene.selected_clip_id = clip_id
        self.session_registry.register(
            clip_id,
            source or "cache",
            url,
            scene.scene_number,
        )

    def _log_candidate_pool(self, scene: SceneRecord, stats: PoolStats) -> None:
        logger.info("Scene %d title: %s", scene.scene_number, scene.title)
        logger.info("Scene %d generated queries: %s", scene.scene_number, scene.queries)
        logger.info("Scene %d results per query: %s", scene.scene_number, stats.results_per_query)
        logger.info("Scene %d candidate pool size: %d", scene.scene_number, stats.pool_size)
        logger.info("Scene %d duplicate count: %d", scene.scene_number, stats.duplicate_count)
        per_query = ", ".join(f"{q!r}: {n}" for q, n in stats.results_per_query.items())
        print(
            f"  Scene {scene.scene_number} ({scene.title}) | "
            f"pool: {stats.pool_size} clips ({stats.duplicate_count} dupes) | "
            f"per query: {per_query}",
            flush=True,
        )

    def _log_scene_selection(
        self,
        scene: SceneRecord,
        ranking: RankingResult,
    ) -> None:
        winner = ranking.winner
        clip = winner.candidate
        clip_id = clip.clip_id or video_hash(clip.url)
        used_label = "YES" if winner.previously_used else "NO"
        logger.info("Scene %d title: %s", scene.scene_number, scene.title)
        logger.info("Scene %d generated queries: %s", scene.scene_number, scene.queries)
        logger.info("Scene %d selected query: %s", scene.scene_number, winner.source_query)
        logger.info("Scene %d selected clip id: %s", scene.scene_number, clip_id)
        logger.info("Scene %d previously used: %s", scene.scene_number, used_label)
        logger.info("Scene %d reason for selection: %s", scene.scene_number, ranking.reason)
        logger.info(
            "Scene %d selected asset: %s (pexels_video)",
            scene.scene_number,
            clip.url,
        )
        print(
            f"  Scene {scene.scene_number} | clip id: {clip_id} | "
            f"Previously Used: {used_label} | "
            f"query: {winner.source_query!r} | final: {winner.final:.3f}",
            flush=True,
        )
        print(f"    Selected query: {winner.source_query!r}", flush=True)
        print(f"    Reason: {ranking.reason}", flush=True)

    def _log_object_query_debug(self, scene: SceneRecord) -> None:
        objects = scene.extracted_objects
        object_labels = objects.summary_labels() if objects else []
        logger.info("Scene %d title: %s", scene.scene_number, scene.title)
        logger.info("Scene %d objects: %s", scene.scene_number, object_labels)
        logger.info("Scene %d generated queries: %s", scene.scene_number, scene.queries)
        print(f"\n  Scene {scene.scene_number} ({scene.title})", flush=True)
        print(f"    Objects: {', '.join(object_labels) or '(none)'}", flush=True)
        print(f"    Generated queries: {scene.queries}", flush=True)
        print(f"    Selected query (initial): {scene.query!r}", flush=True)

    def _log_image_selection(
        self,
        scene: SceneRecord,
        selected_query: str,
        asset_url: str,
        source: str,
    ) -> None:
        logger.info("Scene %d selected query: %s", scene.scene_number, selected_query)
        logger.info("Scene %d selected asset: %s (%s)", scene.scene_number, asset_url, source)
        print(
            f"  Scene {scene.scene_number} | selected query: {selected_query!r} | "
            f"asset: {source}",
            flush=True,
        )

    def _download_scene_asset(self, scene: SceneRecord) -> None:
        url = scene.pending_url
        ext = scene.pending_ext
        if not url or not ext or not scene.asset_kind:
            return

        cached = self.file_cache.get_cached_path(scene.scene_number, url, ext)
        if cached:
            scene.asset_path = cached
            return

        session = requests.Session()
        session.headers["User-Agent"] = "YT-Agent/1.0 (visual-timeline-agent)"
        dest = self.assets_dir / f"scene_{scene.scene_number}{ext}"
        try:
            self._download_file(session, url, dest)
            if scene.asset_kind == "image":
                self._verify_image(dest)
            scene.asset_path = dest
            self.file_cache.record(
                scene.scene_number,
                url,
                dest,
                scene.asset_kind,
                scene.source or "unknown",
            )
            logger.info(
                "Scene %d downloaded (%s) -> %s",
                scene.scene_number,
                scene.source,
                dest,
            )
        except (TimelineAssetError, OSError) as exc:
            logger.error("Scene %d download failed: %s", scene.scene_number, exc)
            # Print a diagnostics block that includes the failure cause.
            self._print_scene_search_diagnostics(
                scene,
                failure_reason=f"Download failure: {exc}",
            )
            scene.asset_path = None
            scene.asset_kind = None
            scene.source = None

    def _persist_topic_cache(self) -> None:
        if not self.topic_cache:
            return
        for scene in self._scenes:
            if scene.asset_path and scene.asset_kind:
                self.topic_cache.save_scene(
                    scene.scene_number,
                    scene.query,
                    scene.asset_path,
                    scene.asset_kind,
                    scene.source or "unknown",
                )

    def _publish_timing(self, *, asset: bool = False, video: bool = False) -> None:
        if not self._timer:
            return
        try:
            from pipeline_timing import PHASE_ASSET_SEARCH, PHASE_VIDEO

            if asset and self._asset_search_seconds > 0:
                self._timer.add(PHASE_ASSET_SEARCH, self._asset_search_seconds)
            if video and self._video_render_seconds > 0:
                self._timer.add(PHASE_VIDEO, self._video_render_seconds)
        except ImportError:
            return
        if self._on_timing_sync:
            self._on_timing_sync()

    def _record_timing_splits(self) -> None:
        self._publish_timing(asset=True, video=True)

    def _download_file(self, session: requests.Session, url: str, output_path: Path) -> None:
        try:
            response = session.get(url, timeout=REQUEST_TIMEOUT, stream=True)
            response.raise_for_status()
            content = response.content
        except requests.RequestException as exc:
            raise TimelineAssetError(f"Download failed: {exc}") from exc

        min_size = 50_000 if output_path.suffix.lower() in (".jpg", ".jpeg") else 100_000
        if len(content) < min_size:
            raise TimelineAssetError(
                f"Downloaded file too small ({len(content)} bytes)."
            )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(content)

    def _verify_image(self, path: Path) -> None:
        try:
            from PIL import Image
        except ImportError as exc:
            raise VisualTimelineAgentError(
                "Pillow is required for image verification. Run: pip install Pillow"
            ) from exc

        with Image.open(path) as img:
            width, height = img.size
            if img.format and img.format.upper() not in ("JPEG", "JPG"):
                img.convert("RGB").save(path, "JPEG", quality=92)
        if width < MIN_IMAGE_WIDTH or height < MIN_IMAGE_HEIGHT:
            path.unlink(missing_ok=True)
            raise TimelineAssetError(
                f"Image {width}x{height} below minimum {MIN_IMAGE_WIDTH}x{MIN_IMAGE_HEIGHT}"
            )

    def _assign_motion_effects(self) -> None:
        for scene in self._scenes:
            if scene.asset_kind == "image":
                scene.motion_effect = random.choice(MOTION_EFFECTS)
                logger.info(
                    "Scene %d image motion: %s (%.2fs)",
                    scene.scene_number,
                    scene.motion_effect,
                    scene.duration_seconds,
                )

    def _render_timeline_segments(self) -> list[Path]:
        assert self._temp_dir is not None
        segment_paths: list[Path] = []

        for scene in self._scenes:
            assert scene.asset_path is not None
            segment_path = self._temp_dir / f"seg_{scene.scene_number:03d}.mp4"
            if scene.asset_kind == "video":
                self._render_video_segment(scene, segment_path)
            else:
                self._render_image_segment(scene, segment_path)
            segment_paths.append(segment_path)

        return segment_paths

    def _render_video_segment(self, scene: SceneRecord, output_path: Path) -> None:
        assert scene.asset_path is not None
        w, h, fps = VIDEO_WIDTH, VIDEO_HEIGHT, VIDEO_FPS
        vf = (
            f"scale={w}:{h}:force_original_aspect_ratio=increase,"
            f"crop={w}:{h},"
            f"setsar=1,fps={fps}"
        )

        trim_start = self._resolve_trim_start(scene)

        command = [self.ffmpeg, "-y"]
        if trim_start > 0:
            # Seek before -i for fast, low-overhead trimming (re-encode follows).
            command += ["-ss", f"{trim_start:.3f}"]
        command += [
            "-i",
            str(scene.asset_path.resolve()),
            "-vf",
            vf,
            "-t",
            str(scene.duration_seconds),
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            "fast",
            "-pix_fmt",
            "yuv420p",
            str(output_path),
        ]
        logger.info(
            "Trimming scene %d video to %.2fs from %.2fs: %s",
            scene.scene_number,
            scene.duration_seconds,
            trim_start,
            scene.asset_path.name,
        )
        self._run_ffmpeg(command, f"video segment {scene.scene_number}")

    def _resolve_trim_start(self, scene: SceneRecord) -> float:
        """Pick a trim start from Florence timeline metadata (Phase 3.7).

        Falls back to 0.0 (current trim-from-start behavior) whenever timeline
        metadata is missing, empty, or all-placeholder.
        """
        assert scene.asset_path is not None
        try:
            clip_duration = probe_duration(scene.asset_path, self.ffprobe)
        except Exception as exc:
            logger.debug("Scene %d: cannot probe clip duration: %s", scene.scene_number, exc)
            return 0.0

        selection = None
        try:
            selection = select_trim_window(
                clip_id_candidates=self._timeline_clip_id_candidates(scene),
                clip_duration=clip_duration,
                narration_duration=scene.duration_seconds,
                scene_tokens=self._scene_tokens(scene),
                metadata_store=self.timeline_metadata_store,
            )
        except Exception as exc:
            logger.debug(
                "Scene %d: timeline segment selection failed: %s",
                scene.scene_number,
                exc,
            )
            return 0.0

        if selection is None:
            logger.info(
                "Scene %d: no timeline metadata; trimming from start (fallback)",
                scene.scene_number,
            )
            return 0.0

        self._log_trim_selection(scene, selection)
        return max(0.0, selection.trim_start)

    def _timeline_clip_id_candidates(self, scene: SceneRecord) -> list[str]:
        """Clip id forms that may key the timeline metadata file."""
        candidates: list[str] = []
        clip_id = (scene.selected_clip_id or "").strip()
        provider = (scene.source or "").split("_")[0] if scene.source else ""
        if clip_id:
            candidates.append(clip_id)
            if provider and not clip_id.startswith(f"{provider}_"):
                candidates.append(f"{provider}_{clip_id}")
        # Deduplicate while preserving order.
        seen: set[str] = set()
        unique: list[str] = []
        for c in candidates:
            if c and c not in seen:
                seen.add(c)
                unique.append(c)
        return unique

    def _scene_tokens(self, scene: SceneRecord) -> set[str]:
        parts = [scene.title, scene.visual_description]
        parts.extend(scene.queries or [])
        if scene.query:
            parts.append(scene.query)
        if scene.extracted_objects:
            parts.extend(scene.extracted_objects.summary_labels())
        tokens: set[str] = set()
        for part in parts:
            tokens |= tokenize(part)
        return tokens

    def _log_trim_selection(self, scene: SceneRecord, selection: TrimSelection) -> None:
        seg = selection.segment
        clip_label = scene.selected_clip_id or scene.selected_asset_url or "?"
        logger.info(
            "Scene %d timeline trim: clip=%s segment=%d/%d [%.2f-%.2f] "
            "trim=[%.2f-%.2f] score=%.3f reason=%s",
            scene.scene_number,
            clip_label,
            selection.segment_index + 1,
            selection.segment_count,
            seg.start,
            seg.end,
            selection.trim_start,
            selection.trim_end,
            selection.score,
            selection.reason,
        )
        print(f"  Scene {scene.scene_number} | timeline-based trim", flush=True)
        print(f"    Selected clip:    {clip_label}", flush=True)
        print(
            f"    Timeline segment: {selection.segment_index + 1}/{selection.segment_count} "
            f"[{seg.start:.2f}s–{seg.end:.2f}s] {seg.description!r}",
            flush=True,
        )
        print(f"    Trim start:       {selection.trim_start:.2f}s", flush=True)
        print(f"    Trim end:         {selection.trim_end:.2f}s", flush=True)
        print(f"    Reason:           {selection.reason}", flush=True)
        print(f"    Similarity score: {selection.score:.3f}", flush=True)

    def _render_image_segment(self, scene: SceneRecord, output_path: Path) -> None:
        assert scene.asset_path is not None
        effect = scene.motion_effect or random.choice(MOTION_EFFECTS)
        frames = max(1, int(round(scene.duration_seconds * VIDEO_FPS)))
        filter_chain = build_motion_filter(effect, frames)
        command = [
            self.ffmpeg,
            "-y",
            "-loop",
            "1",
            "-framerate",
            str(VIDEO_FPS),
            "-i",
            str(scene.asset_path.resolve()),
            "-vf",
            filter_chain,
            "-t",
            str(scene.duration_seconds),
            "-c:v",
            "libx264",
            "-preset",
            "fast",
            "-pix_fmt",
            "yuv420p",
            "-an",
            str(output_path),
        ]
        logger.info(
            "Rendering scene %d image (%s, %.2fs)",
            scene.scene_number,
            effect,
            scene.duration_seconds,
        )
        self._run_ffmpeg(command, f"image segment {scene.scene_number}")

    def _concat_segments(self, segment_paths: list[Path]) -> Path:
        assert self._temp_dir is not None
        concat_list = self._temp_dir / "concat.txt"
        lines = [f"file '{path.resolve().as_posix()}'" for path in segment_paths]
        concat_list.write_text("\n".join(lines) + "\n", encoding="utf-8")

        visual_path = self._temp_dir / "visual_timeline.mp4"
        command = [
            self.ffmpeg,
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_list),
            "-c",
            "copy",
            str(visual_path),
        ]
        self._run_ffmpeg(command, "concat visual timeline (stream copy)")
        logger.info("Visual timeline built: %s", visual_path)
        return visual_path

    def _finalize_with_audio_and_subtitles(self, visual_path: Path) -> None:
        if not self.captions_path.is_file():
            raise CaptionsNotFoundError(
                f"Captions not found: {self.captions_path}. Run Phase 3 first."
            )
        if self.output_path.exists():
            self.output_path.unlink()

        profiler = get_profiler()
        profiler.start(AGENT_SUBTITLE_BURN)
        subtitles = escape_subtitles_path(self.captions_path)
        force_style = build_subtitle_force_style()
        video_filter = f"subtitles={subtitles}:force_style='{force_style}'"
        profiler.end(AGENT_SUBTITLE_BURN)
        profiler.start(AGENT_VIDEO_EXPORT)
        command = [
            self.ffmpeg,
            "-y",
            "-i",
            str(visual_path.resolve()),
            "-i",
            str(self.audio_path.resolve()),
            "-vf",
            video_filter,
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-c:v",
            "libx264",
            "-preset",
            "fast",
            "-crf",
            "23",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-ar",
            "48000",
            "-r",
            str(VIDEO_FPS),
            "-shortest",
            str(self.output_path.resolve()),
        ]
        self._run_ffmpeg(command, "final video with narration and captions")
        profiler.end(AGENT_VIDEO_EXPORT)

    def _run_ffmpeg(self, command: list[str], label: str) -> None:
        timeout = max(120, int(self._narration_seconds) + FFMPEG_TIMEOUT_BUFFER)
        logger.debug("FFmpeg (%s): %s", label, " ".join(command))
        started = time.perf_counter()
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise TimelineRenderError(f"FFmpeg timed out during {label}") from exc
        except OSError as exc:
            raise TimelineRenderError(f"Failed to run FFmpeg for {label}: {exc}") from exc

        elapsed = time.perf_counter() - started
        logger.info(
            "FFmpeg %s completed in %.1fs (code %s)",
            label,
            elapsed,
            result.returncode,
        )
        if result.returncode != 0:
            stderr = (result.stderr or "").strip()
            raise TimelineRenderError(
                f"FFmpeg failed during {label}.\n  stderr: {stderr or '(empty)'}"
            )

    def _verify_output(self) -> None:
        if not self.output_path.is_file():
            raise TimelineRenderError(f"Output video was not created: {self.output_path}")
        if self.output_path.stat().st_size == 0:
            raise TimelineRenderError(f"Output video is empty: {self.output_path}")

    def _print_summary(self, result: TimelineBuildResult) -> None:
        print("\nVisual timeline summary:", flush=True)
        print(f"  Scenes: {result.scene_count}", flush=True)
        print(f"  Stock videos: {result.video_scenes}", flush=True)
        print(f"  Stock images (with motion): {result.image_scenes}", flush=True)
        print(f"  Narration: {result.narration_seconds:.1f}s", flush=True)
        print(f"  Final duration: {result.final_seconds:.1f}s", flush=True)
        print(f"  Output: {result.output_path}", flush=True)
        for scene in self._scenes:
            kind = scene.asset_kind or "?"
            source = scene.source or "?"
            motion = f", {scene.motion_effect}" if scene.motion_effect else ""
            print(
                f"    Scene {scene.scene_number}: {kind} ({source}) "
                f"{scene.duration_seconds:.1f}s{motion}",
                flush=True,
            )
