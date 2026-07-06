"""Extract visual objects from scene metadata and narration via Ollama."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import ollama

from agents.visual_asset_agent import keywords_from_description
from backend.services.scene_understanding.models import ExtractedObjects

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "llama3"
MAX_GENERATION_ATTEMPTS = 2

SYSTEM_PROMPT = """You are a visual research assistant for YouTube Shorts stock footage.
Given a scene title, visual description, and narration excerpt, identify concrete visual objects
that should appear on screen.

You MUST respond with one JSON object:
{
  "primary_objects": ["object one", ...],
  "secondary_objects": ["object two", ...],
  "brands": ["brand name", ...],
  "locations": ["place", ...],
  "mechanical_components": ["part name", ...],
  "historical_figures": ["person name", ...]
}

Rules:
- primary_objects: main subjects the viewer should see (3-6 items)
- secondary_objects: supporting visual elements (0-5 items)
- brands: company or product brands mentioned (empty array if none)
- locations: places, countries, cities, settings (empty array if none)
- mechanical_components: engines, parts, tools, machines (empty array if none)
- historical_figures: named people (empty array if none)
- Use short noun phrases suitable for stock video search
- Focus on what is VISUALLY filmable, not abstract concepts alone
- No markdown, only the JSON object"""

USER_PROMPT_TEMPLATE = """Title: {title}

Visual Description:
{visual_description}

Narration:
{narration_text}

Return JSON with primary_objects, secondary_objects, brands, locations,
mechanical_components, and historical_figures."""


class ObjectExtractorError(Exception):
    """Base error for object extraction."""


class ObjectOllamaConnectionError(ObjectExtractorError):
    """Cannot reach Ollama."""


class ObjectOllamaModelError(ObjectExtractorError):
    """Ollama model unavailable."""


class ObjectExtractionError(ObjectExtractorError):
    """Failed to extract objects."""


class ObjectExtractor:
    """Identify important visual objects discussed in a scene."""

    def __init__(self, model: str = DEFAULT_MODEL) -> None:
        self.model = model

    def extract(
        self,
        title: str,
        visual_description: str,
        narration_text: str,
    ) -> ExtractedObjects:
        title = title.strip()
        visual_description = visual_description.strip()
        narration_text = narration_text.strip()

        if not visual_description and not narration_text:
            raise ObjectExtractionError("visual_description and narration_text are empty")

        last_error: ObjectExtractionError | None = None
        for attempt in range(1, MAX_GENERATION_ATTEMPTS + 1):
            try:
                raw = self._chat(
                    SYSTEM_PROMPT,
                    USER_PROMPT_TEMPLATE.format(
                        title=title or "Scene",
                        visual_description=visual_description or "(none)",
                        narration_text=narration_text or visual_description,
                    ),
                    json_mode=True,
                )
                result = self._parse_objects_json(raw)
                result = self._sanitize(result)
                logger.info(
                    "ObjectExtractor for %r: primary=%s",
                    title,
                    result.primary_objects,
                )
                return result
            except ObjectExtractionError as exc:
                last_error = exc
                logger.warning(
                    "Object extraction attempt %d/%d failed for %r: %s",
                    attempt,
                    MAX_GENERATION_ATTEMPTS,
                    title,
                    exc,
                )

        logger.warning("ObjectExtractor falling back to rule-based extraction for %r", title)
        return self._fallback_extract(title, visual_description, narration_text)

    def _chat(self, system: str, user: str, json_mode: bool = False) -> str:
        chat_kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        if json_mode:
            chat_kwargs["format"] = "json"
            chat_kwargs["options"] = {"num_predict": 512, "temperature": 0.2}

        try:
            response = ollama.chat(**chat_kwargs)
        except ConnectionError as exc:
            raise ObjectOllamaConnectionError(
                "Cannot connect to Ollama. Is it running? (ollama serve)"
            ) from exc
        except Exception as exc:
            err = str(exc).lower()
            if "connection" in err or "refused" in err or "connect" in err:
                raise ObjectOllamaConnectionError(
                    "Cannot connect to Ollama. Is it running? (ollama serve)"
                ) from exc
            if "not found" in err or "model" in err:
                raise ObjectOllamaModelError(
                    f"Model '{self.model}' not available. Run: ollama pull {self.model}"
                ) from exc
            raise ObjectExtractionError(f"Ollama request failed: {exc}") from exc

        message = response.get("message") or {}
        content = (message.get("content") or "").strip()
        if not content:
            raise ObjectExtractionError("Ollama returned an empty response.")
        return content

    @staticmethod
    def _parse_objects_json(raw: str) -> ExtractedObjects:
        text = raw.strip()
        fence = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text, re.IGNORECASE)
        if fence:
            text = fence.group(1).strip()
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ObjectExtractionError(f"Invalid JSON from Ollama: {exc}") from exc

        if not isinstance(data, dict):
            raise ObjectExtractionError("Expected JSON object")

        def _list(key: str) -> list[str]:
            value = data.get(key)
            if not isinstance(value, list):
                return []
            return [str(item).strip() for item in value if str(item).strip()]

        return ExtractedObjects(
            primary_objects=_list("primary_objects"),
            secondary_objects=_list("secondary_objects"),
            brands=_list("brands"),
            locations=_list("locations"),
            mechanical_components=_list("mechanical_components"),
            historical_figures=_list("historical_figures"),
        )

    @classmethod
    def _sanitize(cls, objects: ExtractedObjects) -> ExtractedObjects:
        def clean(items: list[str]) -> list[str]:
            seen: set[str] = set()
            out: list[str] = []
            for item in items:
                normalized = re.sub(r"\s+", " ", item.strip())
                key = normalized.lower()
                if normalized and key not in seen:
                    seen.add(key)
                    out.append(normalized)
            return out

        result = ExtractedObjects(
            primary_objects=clean(objects.primary_objects),
            secondary_objects=clean(objects.secondary_objects),
            brands=clean(objects.brands),
            locations=clean(objects.locations),
            mechanical_components=clean(objects.mechanical_components),
            historical_figures=clean(objects.historical_figures),
        )
        if not result.primary_objects and not result.all_objects():
            raise ObjectExtractionError("No objects in response")
        if not result.primary_objects:
            result.primary_objects = result.all_objects()[:6]
        return result

    @classmethod
    def _fallback_extract(
        cls,
        title: str,
        visual_description: str,
        narration_text: str,
    ) -> ExtractedObjects:
        combined = f"{title} {visual_description} {narration_text}"
        keywords = keywords_from_description(combined, title)
        words = [w for w in keywords.split() if len(w) > 2]
        primary = words[:4] if words else [title] if title else ["scene"]
        secondary = words[4:8]
        return ExtractedObjects(
            primary_objects=primary,
            secondary_objects=secondary,
        )
