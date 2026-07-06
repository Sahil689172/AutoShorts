"""Path and slug helpers for asset library storage."""

from __future__ import annotations

import re
from pathlib import Path

LIBRARY_ROOT = Path("assets/library")
INDEX_DIR = LIBRARY_ROOT / "index"
MASTER_INDEX_PATH = INDEX_DIR / "master_index.json"


def slugify(text: str) -> str:
    """Filesystem-safe slug preserving readable words."""
    text = text.strip()
    text = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE)
    text = re.sub(r"[\s_-]+", " ", text).strip()
    if not text:
        return "misc"
    return " ".join(word.capitalize() for word in text.split())


def topic_dir_name(topic: str) -> str:
    return slugify(topic)


def subtopic_from_query(topic: str, query: str) -> str:
    """Derive subtopic folder name from a search query."""
    topic_lower = topic.strip().lower()
    query_lower = query.strip().lower()
    remainder = query_lower
    if query_lower.startswith(topic_lower):
        remainder = query_lower[len(topic_lower) :].strip()
    if not remainder:
        remainder = query_lower
    return slugify(remainder) or "General"


def library_media_path(topic: str, subtopic: str, asset_id: str, extension: str) -> Path:
    ext = extension if extension.startswith(".") else f".{extension}"
    filename = f"{asset_id}{ext}"
    return LIBRARY_ROOT / topic_dir_name(topic) / subtopic / filename
