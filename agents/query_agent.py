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

    def generate_queries(self, title: str, visual_description: str) -> list[str]:
        """Return 3-5 optimized Pexels search queries for a scene."""
        title = title.strip()
        visual_description = visual_description.strip()
        if not visual_description:
            raise QueryGenerationError("visual_description is empty")

        last_error: QueryGenerationError | None = None
        for attempt in range(1, MAX_GENERATION_ATTEMPTS + 1):
            try:
                raw = self._chat(
                    SYSTEM_PROMPT,
                    USER_PROMPT_TEMPLATE.format(
                        title=title or "Scene",
                        visual_description=visual_description,
                    ),
                    json_mode=True,
                )
                queries = self._parse_queries_json(raw)
                queries = self._sanitize_queries(
                    queries,
                    title=title,
                    visual_description=visual_description,
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
        return self._fallback_queries(title, visual_description)

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

        return cleaned[:MAX_QUERIES]

    @staticmethod
    def _is_too_generic(query: str, context: str) -> bool:
        words = query.split()
        if len(words) == 1 and words[0] in GENERIC_TERMS and words[0] not in context:
            return True
        if len(words) <= 2 and all(word in GENERIC_TERMS for word in words):
            return any(word not in context for word in words)
        return False

    @classmethod
    def _fallback_queries(cls, title: str, visual_description: str) -> list[str]:
        """Rule-based fallback when Ollama output is unusable."""
        primary = keywords_from_description(visual_description, title)
        words = [w for w in primary.split() if w]
        queries: list[str] = []

        if words:
            queries.append(" ".join(words[:MAX_WORDS_PER_QUERY]))

        title_words = [w for w in re.sub(r"[^\w\s]", " ", title.lower()).split() if len(w) > 2]
        if title_words:
            title_query = " ".join(title_words[:MAX_WORDS_PER_QUERY])
            if title_query not in queries:
                queries.append(title_query)

        for start in range(0, len(words), MAX_WORDS_PER_QUERY):
            chunk = " ".join(words[start : start + MAX_WORDS_PER_QUERY])
            if chunk and chunk not in queries:
                queries.append(chunk)
            if len(queries) >= MAX_QUERIES:
                break

        return queries[:MAX_QUERIES]
