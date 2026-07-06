"""Generate stock-footage search queries from scene metadata via Ollama."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import ollama

from agents.visual_asset_agent import keywords_from_description

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "llama3"
MIN_QUERIES = 3
MAX_QUERIES = 5
MAX_WORDS_PER_QUERY = 4
MAX_GENERATION_ATTEMPTS = 2

GENERIC_TERMS = frozenset(
    {
        "car",
        "cars",
        "vehicle",
        "vehicles",
        "transportation",
        "automobile",
        "automobiles",
        "transport",
        "driving",
        "road",
        "roads",
        "street",
        "traffic",
    }
)

SYSTEM_PROMPT = """You are a stock footage search specialist for YouTube Shorts.
Given a scene title and visual description, produce search queries for Pexels video/image search.

You MUST respond with one JSON object:
{"queries": ["query one", "query two", ...]}

Rules:
- Return 3 to 5 queries
- Each query: maximum 4 words
- Queries must be concrete, visual, and searchable (nouns + visual modifiers)
- Prefer specific subjects, actions, settings, and close-ups
- Avoid vague single-word queries
- Avoid generic terms unless the scene explicitly requires them: car, vehicle, transportation, automobile, driving, road, traffic
- No markdown, no explanation, only the JSON object"""

USER_PROMPT_TEMPLATE = """Title: {title}

Visual Description:
{visual_description}

Return JSON with key "queries" containing 3-5 stock footage search strings (max 4 words each)."""

OBJECT_AWARE_USER_PROMPT_TEMPLATE = """Title: {title}

Visual Description:
{visual_description}

Narration:
{narration_text}

Extracted Visual Objects:
{objects_block}

Use the extracted objects above to produce precise stock footage search queries.
Each query should target a specific filmable object or component (max 4 words each).
Return JSON with key "queries" containing 3-5 search strings."""

COLLECTION_SYSTEM_PROMPT = """You are a stock footage librarian building a local media library.
Given a topic, produce diverse search queries for Pexels video search.

You MUST respond with one JSON object:
{"queries": ["query one", "query two", ...]}

Rules:
- Return the requested number of queries (or close to it)
- Each query: maximum 4 words
- Queries must be concrete, visual, and searchable
- Cover different aspects, settings, parts, and actions related to the topic
- Avoid vague single-word queries
- No markdown, no explanation, only the JSON object"""

COLLECTION_USER_PROMPT_TEMPLATE = """Topic: {topic}

Return JSON with key "queries" containing {count} stock footage search strings (max 4 words each).
Include varied angles: locations, components, actions, close-ups, and workshop/context shots where relevant."""

class QueryAgentError(Exception):
    """Base error for query generation."""


class QueryOllamaConnectionError(QueryAgentError):
    """Cannot reach Ollama."""


class QueryOllamaModelError(QueryAgentError):
    """Ollama model unavailable."""


class QueryGenerationError(QueryAgentError):
    """Failed to produce valid queries."""


class QueryAgent:
    """Generate semantic stock search queries for a single scene."""

    def __init__(self, model: str = DEFAULT_MODEL) -> None:
        self.model = model

    def generate_queries(
        self,
        title: str,
        visual_description: str,
        *,
        extracted_objects: Any | None = None,
        narration_text: str = "",
    ) -> list[str]:
        """Return 3-5 optimized Pexels search queries for a scene."""
        title = title.strip()
        visual_description = visual_description.strip()
        narration_text = narration_text.strip()
        if not visual_description:
            raise QueryGenerationError("visual_description is empty")

        objects_block = ""
        if extracted_objects is not None and hasattr(extracted_objects, "to_prompt_block"):
            objects_block = extracted_objects.to_prompt_block()

        use_objects = bool(objects_block.strip())

        last_error: QueryGenerationError | None = None
        for attempt in range(1, MAX_GENERATION_ATTEMPTS + 1):
            try:
                if use_objects:
                    user_prompt = OBJECT_AWARE_USER_PROMPT_TEMPLATE.format(
                        title=title or "Scene",
                        visual_description=visual_description,
                        narration_text=narration_text or "(none)",
                        objects_block=objects_block,
                    )
                else:
                    user_prompt = USER_PROMPT_TEMPLATE.format(
                        title=title or "Scene",
                        visual_description=visual_description,
                    )
                raw = self._chat(
                    SYSTEM_PROMPT,
                    user_prompt,
                    json_mode=True,
                )
                queries = self._parse_queries_json(raw)
                context = f"{title} {visual_description} {narration_text}"
                if extracted_objects is not None:
                    context += " " + " ".join(extracted_objects.all_objects())
                queries = self._sanitize_queries(
                    queries,
                    title=title,
                    visual_description=context,
                )
                if len(queries) < MIN_QUERIES:
                    raise QueryGenerationError(
                        f"Too few valid queries after sanitization ({len(queries)})"
                    )
                logger.info(
                    "QueryAgent produced %d queries for %r: %s",
                    len(queries),
                    title,
                    queries,
                )
                return queries[:MAX_QUERIES]
            except QueryGenerationError as exc:
                last_error = exc
                logger.warning(
                    "Query generation attempt %d/%d failed for %r: %s",
                    attempt,
                    MAX_GENERATION_ATTEMPTS,
                    title,
                    exc,
                )

        logger.warning(
            "QueryAgent falling back to rule-based queries for %r",
            title,
        )
        return self._fallback_queries(
            title,
            visual_description,
            extracted_objects=extracted_objects,
        )

    def generate_topic_queries(self, topic: str, count: int = 10) -> list[str]:
        """Return search queries for offline asset collection on a topic."""
        topic = topic.strip()
        if not topic:
            raise QueryGenerationError("topic is empty")
        count = max(3, min(count, 30))

        description = (
            f"Build a stock footage library for the topic {topic}. "
            f"Include factory, assembly, components, logos, interiors, "
            f"workshop, driving, and detail shots where relevant."
        )

        last_error: QueryGenerationError | None = None
        for attempt in range(1, MAX_GENERATION_ATTEMPTS + 1):
            try:
                raw = self._chat(
                    COLLECTION_SYSTEM_PROMPT,
                    COLLECTION_USER_PROMPT_TEMPLATE.format(topic=topic, count=count),
                    json_mode=True,
                )
                queries = self._parse_queries_json(raw)
                queries = self._sanitize_queries(
                    queries,
                    title=topic,
                    visual_description=description,
                    max_queries=count,
                )
                if len(queries) < 3:
                    raise QueryGenerationError(
                        f"Too few topic queries after sanitization ({len(queries)})"
                    )
                logger.info(
                    "QueryAgent produced %d topic queries for %r",
                    len(queries),
                    topic,
                )
                return queries[:count]
            except QueryGenerationError as exc:
                last_error = exc
                logger.warning(
                    "Topic query generation attempt %d/%d failed for %r: %s",
                    attempt,
                    MAX_GENERATION_ATTEMPTS,
                    topic,
                    exc,
                )

        logger.warning("QueryAgent falling back to rule-based topic queries for %r", topic)
        return self._fallback_topic_queries(topic, count)

    @classmethod
    def _fallback_topic_queries(cls, topic: str, count: int) -> list[str]:
        """Rule-based topic queries when Ollama is unavailable."""
        base = topic.strip().lower()
        suffixes = [
            "factory",
            "assembly",
            "engine",
            "logo",
            "interior",
            "exhaust",
            "workshop",
            "driving",
            "close up",
            "detail",
            "manufacturing",
            "showroom",
        ]
        queries: list[str] = []
        seen: set[str] = set()
        for suffix in suffixes:
            words = f"{base} {suffix}".split()
            q = " ".join(words[:MAX_WORDS_PER_QUERY])
            if q not in seen:
                seen.add(q)
                queries.append(q)
            if len(queries) >= count:
                break
        return queries[:count]

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
            raise QueryOllamaConnectionError(
                "Cannot connect to Ollama. Is it running? (ollama serve)"
            ) from exc
        except Exception as exc:
            err = str(exc).lower()
            if "connection" in err or "refused" in err or "connect" in err:
                raise QueryOllamaConnectionError(
                    "Cannot connect to Ollama. Is it running? (ollama serve)"
                ) from exc
            if "not found" in err or "model" in err:
                raise QueryOllamaModelError(
                    f"Model '{self.model}' not available. Run: ollama pull {self.model}"
                ) from exc
            raise QueryGenerationError(f"Ollama request failed: {exc}") from exc

        message = response.get("message") or {}
        content = (message.get("content") or "").strip()
        if not content:
            raise QueryGenerationError("Ollama returned an empty response.")
        return content

    @staticmethod
    def _parse_queries_json(raw: str) -> list[str]:
        text = raw.strip()
        fence = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text, re.IGNORECASE)
        if fence:
            text = fence.group(1).strip()
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise QueryGenerationError(f"Invalid JSON from Ollama: {exc}") from exc

        if isinstance(data, dict):
            queries = data.get("queries")
        elif isinstance(data, list):
            queries = data
        else:
            raise QueryGenerationError("Expected JSON object with 'queries' array")

        if not isinstance(queries, list):
            raise QueryGenerationError("'queries' must be an array")

        result: list[str] = []
        for item in queries:
            if isinstance(item, str) and item.strip():
                result.append(item.strip())
        if not result:
            raise QueryGenerationError("No query strings in response")
        return result

    @classmethod
    def _sanitize_queries(
        cls,
        queries: list[str],
        *,
        title: str,
        visual_description: str,
        max_queries: int = MAX_QUERIES,
    ) -> list[str]:
        context = f"{title} {visual_description}".lower()
        cleaned: list[str] = []
        seen: set[str] = set()

        for query in queries:
            normalized = re.sub(r"\s+", " ", query.strip().lower())
            normalized = re.sub(r"[^\w\s]", " ", normalized).strip()
            if not normalized:
                continue
            words = normalized.split()
            if len(words) > MAX_WORDS_PER_QUERY:
                words = words[:MAX_WORDS_PER_QUERY]
                normalized = " ".join(words)
            if not normalized or normalized in seen:
                continue
            if cls._is_too_generic(normalized, context):
                continue
            seen.add(normalized)
            cleaned.append(normalized)

        if len(cleaned) < MIN_QUERIES:
            for extra in cls._fallback_queries(title, visual_description):
                if extra not in seen and not cls._is_too_generic(extra, context):
                    cleaned.append(extra)
                    seen.add(extra)
                if len(cleaned) >= MIN_QUERIES:
                    break

        return cleaned[:max_queries]

    @staticmethod
    def _is_too_generic(query: str, context: str) -> bool:
        words = query.split()
        if len(words) == 1 and words[0] in GENERIC_TERMS and words[0] not in context:
            return True
        if len(words) <= 2 and all(word in GENERIC_TERMS for word in words):
            return any(word not in context for word in words)
        return False

    @classmethod
    def _fallback_queries(
        cls,
        title: str,
        visual_description: str,
        *,
        extracted_objects: Any | None = None,
    ) -> list[str]:
        """Rule-based fallback when Ollama output is unusable."""
        queries: list[str] = []
        seen: set[str] = set()

        if extracted_objects is not None:
            for obj in extracted_objects.primary_objects[:MAX_QUERIES]:
                words = obj.split()[:MAX_WORDS_PER_QUERY]
                q = " ".join(words)
                if q and q not in seen:
                    seen.add(q)
                    queries.append(q)
            for obj in extracted_objects.mechanical_components:
                if len(queries) >= MAX_QUERIES:
                    break
                words = obj.split()[:MAX_WORDS_PER_QUERY]
                q = " ".join(words)
                if q and q not in seen:
                    seen.add(q)
                    queries.append(q)

        if len(queries) >= MIN_QUERIES:
            return queries[:MAX_QUERIES]

        primary = keywords_from_description(visual_description, title)
        words = [w for w in primary.split() if w]

        if words:
            q = " ".join(words[:MAX_WORDS_PER_QUERY])
            if q not in seen:
                queries.append(q)
                seen.add(q)

        title_words = [w for w in re.sub(r"[^\w\s]", " ", title.lower()).split() if len(w) > 2]
        if title_words:
            title_query = " ".join(title_words[:MAX_WORDS_PER_QUERY])
            if title_query not in seen:
                queries.append(title_query)
                seen.add(title_query)

        for start in range(0, len(words), MAX_WORDS_PER_QUERY):
            chunk = " ".join(words[start : start + MAX_WORDS_PER_QUERY])
            if chunk and chunk not in seen:
                queries.append(chunk)
                seen.add(chunk)
            if len(queries) >= MAX_QUERIES:
                break

        return queries[:MAX_QUERIES]
