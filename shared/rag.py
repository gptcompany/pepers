"""Shared helpers for RAGAnything integration."""

from __future__ import annotations

RAG_FORCE_PARSERS = frozenset({"mineru", "docling", "paddleocr"})


def normalize_rag_force_parser(value: object) -> str | None:
    """Normalize an optional parser override for RAGAnything.

    Returns None for missing/blank values and lowercases valid parser names.
    Raises ValueError for invalid inputs so HTTP handlers can return 400s.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("force_parser must be a string")

    normalized = value.strip().lower()
    if not normalized:
        return None
    if normalized not in RAG_FORCE_PARSERS:
        allowed = ", ".join(sorted(RAG_FORCE_PARSERS))
        raise ValueError(f"force_parser must be one of: {allowed}")
    return normalized
