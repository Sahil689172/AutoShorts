"""Build placeholder timeline segments for clips (pre-Florence-2)."""

from __future__ import annotations

from backend.services.clip_intelligence.models import TimelineSegment


class TimelineBuilder:
    """Construct timeline segment lists from clip duration."""

    def build_placeholder(self, duration: float) -> list[TimelineSegment]:
        """Single full-clip segment with unknown content (Phase 3.5)."""
        safe_duration = max(0.0, float(duration))
        return [
            TimelineSegment(
                start=0.0,
                end=safe_duration,
                description="Unknown",
                objects=[],
                confidence=0.0,
            )
        ]

    def build_segments(
        self,
        duration: float,
        *,
        segment_length: float = 5.0,
    ) -> list[TimelineSegment]:
        """
        Split duration into fixed-length placeholder segments.

        Reserved for future keyframe-aligned segmentation.
        """
        if duration <= 0:
            return self.build_placeholder(duration)

        segments: list[TimelineSegment] = []
        start = 0.0
        while start < duration:
            end = min(start + segment_length, duration)
            segments.append(
                TimelineSegment(
                    start=start,
                    end=end,
                    description="Unknown",
                    objects=[],
                    confidence=0.0,
                )
            )
            start = end
        return segments or self.build_placeholder(duration)
