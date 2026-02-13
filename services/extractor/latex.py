"""LaTeX formula extraction engine.

Multi-pass regex extraction with occupied-span tracking to prevent
overlapping matches. Extracts formulas from markdown text produced
by RAGAnything.

5 passes in priority order:
1. Named math environments (equation, align, gather, etc.)
2. Display brackets \\[...\\]
3. Display dollars $$...$$
4. Inline parens \\(...\\)
5. Inline dollars $...$
"""

from __future__ import annotations

import hashlib
import re

from shared.models import Formula

MATH_ENV_NAMES = (
    "equation", "align", "gather", "multline",
    "flalign", "eqnarray", "displaymath", "math",
    "aligned", "gathered",
)

MIN_FORMULA_LENGTH = 3
CONTEXT_WINDOW = 200

# Pass 1: Named math environments
PATTERN_NAMED_ENV = re.compile(
    r"\\begin\{(" + "|".join(MATH_ENV_NAMES) + r")\*?\}"
    r"(.*?)"
    r"\\end\{\1\*?\}",
    re.DOTALL,
)

# Pass 2: \[...\]
PATTERN_DISPLAY_BRACKET = re.compile(r"\\\[(.*?)\\\]", re.DOTALL)

# Pass 3: $$...$$
PATTERN_DISPLAY_DOLLAR = re.compile(r"\$\$(.*?)\$\$", re.DOTALL)

# Pass 4: \(...\)
PATTERN_INLINE_PAREN = re.compile(r"\\\((.*?)\\\)", re.DOTALL)

# Pass 5: $...$ (most ambiguous, lowest priority)
PATTERN_INLINE_DOLLAR = re.compile(
    r"(?<!\\)"      # not escaped \$
    r"(?<!\$)"      # not part of $$
    r"\$"
    r"(?!\$)"       # not $$
    r"(?!\s)"       # no leading space
    r"([^\$\n]+?)"  # content (non-greedy, single line)
    r"(?<!\s)"      # no trailing space
    r"\$"
    r"(?!\$)",      # not $$
)


def extract_formulas(text: str) -> list[dict]:
    """Multi-pass extraction with occupied-span tracking.

    Returns list of dicts with keys: latex, formula_type, start, end.
    """
    formulas: list[dict] = []
    occupied: set[int] = set()

    def _add(latex: str, ftype: str, start: int, end: int) -> None:
        span = set(range(start, end))
        if not span & occupied:
            occupied.update(span)
            formulas.append({
                "latex": latex.strip(),
                "formula_type": ftype,
                "start": start,
                "end": end,
            })

    # Pass 1: Named environments
    for m in PATTERN_NAMED_ENV.finditer(text):
        ftype = "display" if m.group(1) != "math" else "inline"
        _add(m.group(2), ftype, m.start(), m.end())

    # Pass 2: \[...\]
    for m in PATTERN_DISPLAY_BRACKET.finditer(text):
        _add(m.group(1), "display", m.start(), m.end())

    # Pass 3: $$...$$
    for m in PATTERN_DISPLAY_DOLLAR.finditer(text):
        _add(m.group(1), "display", m.start(), m.end())

    # Pass 4: \(...\)
    for m in PATTERN_INLINE_PAREN.finditer(text):
        _add(m.group(1), "inline", m.start(), m.end())

    # Pass 5: $...$
    for m in PATTERN_INLINE_DOLLAR.finditer(text):
        _add(m.group(1), "inline", m.start(), m.end())

    formulas.sort(key=lambda f: f["start"])
    return formulas


def extract_context(
    text: str, start: int, end: int, window: int = CONTEXT_WINDOW
) -> str:
    """Extract surrounding text for a formula."""
    ctx_start = max(0, start - window)
    ctx_end = min(len(text), end + window)
    return text[ctx_start:ctx_end].strip()


def filter_formulas(formulas: list[dict]) -> list[dict]:
    """Remove trivial and duplicate formulas."""
    seen_hashes: set[str] = set()
    filtered: list[dict] = []

    for f in formulas:
        latex = f["latex"]

        # Skip trivially short
        if len(latex.strip()) < MIN_FORMULA_LENGTH:
            continue

        # Skip non-math (no LaTeX commands or braces)
        if "\\" not in latex and "{" not in latex:
            continue

        # Deduplicate by hash
        h = hashlib.sha256(latex.encode()).hexdigest()
        if h in seen_hashes:
            continue
        seen_hashes.add(h)

        filtered.append(f)

    return filtered


def formulas_to_models(
    paper_id: int, text: str, raw_formulas: list[dict]
) -> list[Formula]:
    """Convert extracted formulas to Pydantic models."""
    return [
        Formula(
            paper_id=paper_id,
            latex=f["latex"],
            formula_type=f["formula_type"],
            context=extract_context(text, f["start"], f["end"]),
        )
        for f in raw_formulas
    ]
