"""CLI entry point for YouTube Shorts pipeline: script through final video."""

import logging
import sys

from agents.scene_agent import (
    SceneAgent,
    SceneAgentError,
    SceneGenerationError,
    SceneOllamaConnectionError,
    SceneOllamaModelError,
    SceneValidationError,
    ScriptNotFoundError as SceneScriptNotFoundError,
)
from agents.visual_asset_agent import APIKeyMissingError
from agents.visual_timeline_agent import (
    CaptionsNotFoundError as TimelineCaptionsNotFoundError,
    FFmpegNotFoundError as TimelineFFmpegNotFoundError,
    NarrationNotFoundError,
    ScenesNotFoundError as TimelineScenesNotFoundError,
    TimelineAssetError,
    TimelineRenderError,
    VisualTimelineAgent,
    VisualTimelineAgentError,
)
from caption_generator import (
    AudioNotFoundError,
    CaptionGenerationError,
    CaptionGenerator,
    CaptionGeneratorError,
    FFmpegNotFoundError,
    WhisperModelLoadError,
    WhisperPackageNotFoundError,
)
from metadata_generator import (
    MetadataGenerator,
    MetadataGeneratorError,
    MetadataOllamaConnectionError,
    MetadataOllamaModelError,
    MetadataValidationError,
)
from script_generator import (
    MAX_WORDS,
    MIN_WORDS,
    TARGET_MAX_WORDS,
    TARGET_MIN_WORDS,
    OllamaConnectionError,
    OllamaModelError,
    ScriptGenerator,
    ScriptGeneratorError,
    ScriptValidationError,
)
from backend.services.narration.exceptions import NarrationError, NarratorNotFoundError, ScriptNotFoundError
from voice_generator import VoiceGenerator
from pipeline_timing import (
    PHASE_CAPTIONS,
    PHASE_METADATA,
    PHASE_SCENES,
    PHASE_SCRIPT_GENERATION,
    PHASE_VOICE,
    PipelineTimer,
)

from backend.logging_config import _configure_stdio_utf8

_configure_stdio_utf8()
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def read_topic() -> str:
    """Read topic from command-line args or interactive prompt."""
    if len(sys.argv) > 1:
        return " ".join(sys.argv[1:]).strip()
    try:
        return input("Enter YouTube Shorts topic: ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\nCancelled.", file=sys.stderr)
        sys.exit(130)


def main() -> int:
    topic = read_topic()
    if not topic:
        print("Error: Topic cannot be empty.", file=sys.stderr)
        return 1

    timer = PipelineTimer()
    from pipeline_timing import log_optimization_banner

    log_optimization_banner()
    script_generator = ScriptGenerator()
    metadata_generator = MetadataGenerator()
    voice_generator = VoiceGenerator()
    caption_generator = CaptionGenerator()
    scene_agent = SceneAgent()
    visual_timeline_agent = VisualTimelineAgent(topic=topic, timer=timer)
    try:
        with timer.track(PHASE_SCRIPT_GENERATION):
            logger.info("Phase 1: generating script")
            script, raw_path, formatted_path = script_generator.generate_and_save(topic)
    except OllamaConnectionError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except OllamaModelError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except ScriptValidationError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except ScriptGeneratorError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    word_count = len(script.split())
    if MIN_WORDS <= word_count <= MAX_WORDS:
        range_note = f"{MIN_WORDS}-{MAX_WORDS} words (30-45s target)"
    else:
        range_note = f"outside {MIN_WORDS}-{MAX_WORDS}"
    print(f"Script saved — final word count: {word_count} ({range_note})")
    print(f"  Readable: {formatted_path}")
    print(f"  Debug:    {raw_path}")

    try:
        with timer.track(PHASE_METADATA):
            logger.info("Phase 1: generating metadata")
            metadata, title_path, description_path = (
                metadata_generator.generate_and_save(script, topic)
            )
    except MetadataOllamaConnectionError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except MetadataOllamaModelError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except MetadataValidationError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        print("Tip: Try running again; model output can vary.", file=sys.stderr)
        return 1
    except MetadataGeneratorError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print("Metadata saved")
    print(f"  Title:       {title_path}")
    print(f"  Description: {description_path} (includes 10 hashtags)")
    print(f"  Title preview: {metadata.title}")

    try:
        with timer.track(PHASE_VOICE):
            logger.info("Phase 2: generating voice narration")
            print("\nPhase 2 — Voice generation")
            audio_path = voice_generator.generate()
    except NarratorNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except ScriptNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except NarrationError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(f"\nVoice saved -> {audio_path}")

    try:
        with timer.track(PHASE_CAPTIONS):
            logger.info("Phase 3: generating captions")
            print("\nPhase 3 — Caption generation")
            srt_path = caption_generator.generate()
    except AudioNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except FFmpegNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except WhisperPackageNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except WhisperModelLoadError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except CaptionGenerationError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except CaptionGeneratorError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(f"\nCaptions saved -> {srt_path}")

    try:
        with timer.track(PHASE_SCENES):
            logger.info("Phase 4.5A: generating visual scenes")
            print("\nPhase 4.5A — Scene Agent")
            _, scenes_path = scene_agent.generate()
    except SceneScriptNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except SceneOllamaConnectionError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except SceneOllamaModelError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except SceneValidationError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        print("Tip: Try running again; model output can vary.", file=sys.stderr)
        return 1
    except SceneGenerationError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except SceneAgentError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(f"\nScenes saved -> {scenes_path}")

    try:
        logger.info("Phase 4.5B: building video-first visual timeline")
        print("\nPhase 4.5B — Visual Timeline Agent")
        result = visual_timeline_agent.generate()
    except TimelineScenesNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except APIKeyMissingError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except NarrationNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except TimelineCaptionsNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except TimelineFFmpegNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except TimelineAssetError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except TimelineRenderError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except VisualTimelineAgentError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(f"\nVideo saved -> {result.output_path}")
    print(
        f"  ({result.video_scenes} video clips, {result.image_scenes} motion images)",
        flush=True,
    )

    timer.log_summary()
    return 0


if __name__ == "__main__":
    sys.exit(main())
