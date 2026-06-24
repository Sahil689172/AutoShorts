"""Shared narration text preparation."""

from __future__ import annotations

import re


def prepare_narration_text(text: str) -> str:
    """Flatten formatted script lines into narration-friendly text."""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n+", text.strip()) if p.strip()]
    if not paragraphs:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        return " ".join(lines)
    return " ".join(re.sub(r"\s+", " ", paragraph) for paragraph in paragraphs)
