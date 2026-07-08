"""Narration sanitization for speech synthesis (Phase 3.7E).

This module cleans narration text immediately before TTS generation to improve
Kokoro long-form stability without changing the TTS provider implementation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


_URL_RE = re.compile(r"(https?://[^\s]+)", re.IGNORECASE)


@dataclass(frozen=True)
class SanitizerDebug:
    characters_before: int
    characters_after: int
    sentence_count: int
    chunk_count: int
    longest_chunk: int

    def format_lines(self) -> list[str]:
        return [
            "NarrationSanitizer debug:",
            f"  Characters Before: {self.characters_before}",
            f"  Characters After:  {self.characters_after}",
            f"  Sentence Count:    {self.sentence_count}",
            f"  Chunk Count:       {self.chunk_count}",
            f"  Longest Chunk:     {self.longest_chunk}",
        ]


class NarrationSanitizer:
    """Sanitize narration text for speech synthesis."""

    def sanitize(self, raw: str) -> str:
        text = (raw or "").strip()
        if not text:
            return ""

        # 1) Normalize whitespace early for stable regex behavior.
        text = re.sub(r"\s+", " ", text).strip()

        # 2) Normalize repeated punctuation.
        text = re.sub(r"\.{2,}", ".", text)
        text = re.sub(r"!{2,}", "!", text)
        text = re.sub(r"\?{2,}", "?", text)

        # 3) Protect URLs from punctuation fixes that would introduce spaces.
        text, url_map = self._mask_urls(text)

        # 4) Insert missing whitespace after sentence-ending punctuation.
        #    Examples: ".Inside" -> ". Inside", "RPM.The" -> "RPM. The"
        #    Safeguards:
        #    - Do not split decimals (e.g. "3.14")
        #    - Do not touch ellipsis already normalized above
        text = self._insert_space_after_sentence_punct(text)

        # 5) Remove duplicate whitespace again (after insertions).
        text = re.sub(r"\s+", " ", text).strip()

        # 6) Restore URLs.
        text = self._unmask_urls(text, url_map)

        return text

    def debug_stats(self, raw: str, sanitized: str, *, max_chunk_chars: int = 400) -> SanitizerDebug:
        sentences = self._split_sentences(sanitized)
        chunks = self._estimate_chunks_for_kokoro(sanitized, max_chunk_chars=max_chunk_chars)
        longest = max((len(c) for c in chunks), default=0)
        return SanitizerDebug(
            characters_before=len(raw or ""),
            characters_after=len(sanitized or ""),
            sentence_count=len([s for s in sentences if s]),
            chunk_count=len(chunks),
            longest_chunk=longest,
        )

    @staticmethod
    def _mask_urls(text: str) -> tuple[str, dict[str, str]]:
        url_map: dict[str, str] = {}

        def repl(match: re.Match[str]) -> str:
            url = match.group(1)
            token = f"__URL_{len(url_map)}__"
            url_map[token] = url
            return token

        return _URL_RE.sub(repl, text), url_map

    @staticmethod
    def _unmask_urls(text: str, url_map: dict[str, str]) -> str:
        for token, url in url_map.items():
            text = text.replace(token, url)
        return text

    @staticmethod
    def _insert_space_after_sentence_punct(text: str) -> str:
        # Insert a space after ., !, ? when immediately followed by a letter/number,
        # unless it's a decimal number (digit . digit).
        def repl(match: re.Match[str]) -> str:
            punct = match.group(1)
            nxt = match.group(2)
            return f"{punct} {nxt}"

        # Case: <punct><letter|digit> with no whitespace.
        # Exclude decimals: (?<!\d)\.(?!\d) isn't sufficient because we want to allow "RPM.The"
        # but block "3.14". We do this by rejecting digit-before-and-after only.
        pattern = re.compile(r"([.!?])([A-Za-z0-9])")

        def guarded(m: re.Match[str]) -> str:
            idx = m.start(1)
            prev = text[idx - 1] if idx - 1 >= 0 else ""
            punct = m.group(1)
            nxt = m.group(2)
            if punct == "." and prev.isdigit() and nxt.isdigit():
                return m.group(0)  # decimal, keep as-is
            return repl(m)

        return pattern.sub(guarded, text)

    @staticmethod
    def _split_sentences(text: str) -> list[str]:
        # Simple sentence split; robust chunking happens later.
        return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s.strip()]

    @staticmethod
    def _estimate_chunks_for_kokoro(text: str, *, max_chunk_chars: int) -> list[str]:
        """
        Estimate chunking behavior for debug prints.

        Uses the same splitting priority required by Phase 3.7E:
        sentence boundaries → comma/semicolon/colon → whitespace.
        """
        if not text.strip():
            return []

        # Sentence-like pieces.
        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s.strip()]
        atoms: list[str] = []
        for sent in sentences:
            if len(sent) <= max_chunk_chars:
                atoms.append(sent)
                continue

            # Split oversized "sentence" by , ; :
            parts = [p.strip() for p in re.split(r"\s*[,;:]\s*", sent) if p.strip()]
            if not parts:
                parts = [sent]
            for part in parts:
                if len(part) <= max_chunk_chars:
                    atoms.append(part)
                else:
                    # Final fallback: whitespace (words), then hard cut.
                    words = part.split()
                    if not words:
                        continue
                    buf = ""
                    for w in words:
                        cand = f"{buf} {w}".strip() if buf else w
                        if len(cand) <= max_chunk_chars:
                            buf = cand
                        else:
                            if buf:
                                atoms.append(buf)
                            buf = w
                    if buf:
                        atoms.append(buf)

        # Greedy pack atoms into chunks <= max_chunk_chars.
        chunks: list[str] = []
        buf = ""
        for atom in atoms:
            cand = f"{buf} {atom}".strip() if buf else atom
            if len(cand) <= max_chunk_chars:
                buf = cand
            else:
                if buf:
                    chunks.append(buf)
                buf = atom
        if buf:
            chunks.append(buf)
        return chunks

