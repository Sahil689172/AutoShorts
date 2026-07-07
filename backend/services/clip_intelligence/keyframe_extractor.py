"""Extract representative keyframes for Florence analysis."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Keyframe:
    """A single extracted frame reference."""

    timestamp: float
    image: Image.Image


class KeyframeExtractor:
    """
    Extract representative frames from a clip.

    Phase 3.6:
    - Uses PySceneDetect to detect shots.
    - Extracts one representative frame (midpoint) per shot using OpenCV.
    """

    def extract(self, video_path: Path, duration: float) -> list[Keyframe]:
        if not video_path.is_file():
            logger.debug("Keyframe extraction skipped; file missing: %s", video_path)
            return []

        scenes = self._detect_scenes(video_path)
        if not scenes:
            # Fallback: single full-duration shot.
            scenes = [(0.0, max(0.0, float(duration)))]

        keyframes: list[Keyframe] = []
        for start, end in scenes:
            ts = max(0.0, (float(start) + float(end)) / 2.0)
            img = self._frame_at(video_path, ts)
            if img is None:
                continue
            keyframes.append(Keyframe(timestamp=ts, image=img))
        return keyframes

    @staticmethod
    def _detect_scenes(video_path: Path) -> list[tuple[float, float]]:
        """
        Returns list of (start_seconds, end_seconds).
        """
        try:
            # Newer scenedetect API
            from scenedetect import SceneManager, open_video
            from scenedetect.detectors import ContentDetector

            video = open_video(str(video_path))
            scene_manager = SceneManager()
            scene_manager.add_detector(ContentDetector())
            scene_manager.detect_scenes(video)
            scene_list = scene_manager.get_scene_list()
            scenes: list[tuple[float, float]] = []
            for start_time, end_time in scene_list:
                scenes.append((start_time.get_seconds(), end_time.get_seconds()))
            return scenes
        except Exception as exc:
            logger.warning("PySceneDetect failed for %s: %s", video_path.name, exc)
            return []

    @staticmethod
    def _frame_at(video_path: Path, timestamp: float) -> Image.Image | None:
        """
        Extract frame at timestamp using OpenCV and return as PIL Image (RGB).
        """
        try:
            import cv2  # type: ignore
        except Exception as exc:
            logger.warning("OpenCV not available; cannot extract keyframes: %s", exc)
            return None

        cap = cv2.VideoCapture(str(video_path))
        try:
            if not cap.isOpened():
                return None
            cap.set(cv2.CAP_PROP_POS_MSEC, float(timestamp) * 1000.0)
            ok, frame = cap.read()
            if not ok or frame is None:
                return None
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            return Image.fromarray(frame_rgb)
        finally:
            cap.release()
