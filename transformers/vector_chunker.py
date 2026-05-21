"""Chunk unstructured text (42 CFR Part 8, SAMHSA TIP 63, etc.) for the RAG vector DB.

Engine 2's NLP layer is RAG-backed: the agent retrieves the most relevant guideline
chunks at inference time, rather than baking them into the model. We produce small,
overlapping chunks with stable IDs so re-runs only re-embed what actually changed.
"""
from __future__ import annotations

import hashlib
import re
from typing import Iterable

from scrapers.base import ScrapeResult

DEFAULT_CHUNK_CHARS = 1200
DEFAULT_OVERLAP_CHARS = 150


def _split_paragraphs(text: str) -> list[str]:
    parts = re.split(r"\n\s*\n", text.strip())
    return [p.strip() for p in parts if p.strip()]


def _window(text: str, size: int, overlap: int) -> Iterable[str]:
    if len(text) <= size:
        yield text
        return
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        yield text[start:end]
        if end == len(text):
            return
        start = end - overlap


def chunk_for_rag(
    results: Iterable[ScrapeResult],
    *,
    chunk_chars: int = DEFAULT_CHUNK_CHARS,
    overlap_chars: int = DEFAULT_OVERLAP_CHARS,
) -> list[dict]:
    chunks: list[dict] = []
    for r in results:
        # eCFR scraper produces per-section structured chunks already.
        sections = r.parsed.get("sections") if isinstance(r.parsed, dict) else None
        if sections:
            for s in sections:
                _emit_chunks(
                    chunks,
                    text=s.get("text", "") or "",
                    source_key=r.source_key,
                    label=f"{s.get('id', '?')} {s.get('label', '')}",
                    chunk_chars=chunk_chars,
                    overlap_chars=overlap_chars,
                )
            continue
        # Free-form PDFs (TIP 63, AHCA handbook) — paragraph-split then window.
        text = r.parsed.get("full_text") or r.parsed.get("raw_excerpt") or ""
        for para in _split_paragraphs(text):
            _emit_chunks(
                chunks,
                text=para,
                source_key=r.source_key,
                label=r.source_name,
                chunk_chars=chunk_chars,
                overlap_chars=overlap_chars,
            )
    return chunks


def _emit_chunks(
    acc: list[dict],
    *,
    text: str,
    source_key: str,
    label: str,
    chunk_chars: int,
    overlap_chars: int,
) -> None:
    for piece in _window(text, chunk_chars, overlap_chars):
        chunk_id = hashlib.sha256(f"{source_key}|{label}|{piece}".encode()).hexdigest()[:16]
        acc.append(
            {
                "chunk_id": chunk_id,
                "source_key": source_key,
                "label": label,
                "text": piece,
                "char_count": len(piece),
            }
        )
