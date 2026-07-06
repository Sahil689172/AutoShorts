"""Map full narration script to per-scene text segments."""

from __future__ import annotations


def map_narration_to_scenes(
    script: str,
    scenes: list,
) -> dict[int, str]:
    """
    Split narration proportionally by scene duration.

    scenes: objects with scene_number and duration_seconds attributes.
    """
    text = script.strip()
    if not text or not scenes:
        return {}

    words = text.split()
    if not words:
        return {}

    total_duration = sum(getattr(s, "duration_seconds", 0) or 0 for s in scenes)
    if total_duration <= 0:
        per_scene = max(1, len(words) // len(scenes))
        segments: dict[int, str] = {}
        idx = 0
        sorted_scenes = sorted(scenes, key=lambda s: s.scene_number)
        for i, scene in enumerate(sorted_scenes):
            if i == len(sorted_scenes) - 1:
                chunk = words[idx:]
            else:
                chunk = words[idx : idx + per_scene]
                idx += per_scene
            segments[scene.scene_number] = " ".join(chunk)
        return segments

    segments = {}
    idx = 0
    sorted_scenes = sorted(scenes, key=lambda s: s.scene_number)
    for i, scene in enumerate(sorted_scenes):
        if i == len(sorted_scenes) - 1:
            chunk = words[idx:]
        else:
            fraction = scene.duration_seconds / total_duration
            count = max(1, int(len(words) * fraction))
            chunk = words[idx : idx + count]
            idx += count
        segments[scene.scene_number] = " ".join(chunk)

    return segments
