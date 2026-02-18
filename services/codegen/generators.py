"""SymPy-based code generation for validated formulas.

Transforms LaTeX strings into executable code in three languages:
- C99 (primary) via codegen("C99")
- Rust (secondary) via codegen("Rust")
- Python (always) via pycode()

Uses SymPy's parse_latex (ANTLR backend) for LaTeX→Expr conversion.
Per-language error isolation: one failure doesn't block others.
"""

from __future__ import annotations

import json
import logging
import os
import re

import sympy
from sympy.parsing.latex import parse_latex
from sympy.printing.pycode import pycode
from sympy.utilities.codegen import codegen

from shared.models import LLMCodegenResult

logger = logging.getLogger(__name__)

CODEGEN_FALLBACK_ORDER = os.environ.get(
    "RP_CODEGEN_FALLBACK_ORDER",
    os.environ.get("RP_LLM_FALLBACK_ORDER", "gemini_cli,codex_cli,claude_cli,openrouter,ollama"),
).split(",")

_LLM_CODEGEN_SYSTEM = """You are a mathematical code generator. Given a LaTeX formula,
produce equivalent Python/numpy code.

Respond ONLY with valid JSON matching this schema:
{
  "python_code": "<single Python expression using math/numpy functions>",
  "variables": ["<list of free variable names>"],
  "description": "<one-sentence description>"
}

Rules:
1. Use numpy functions (np.exp, np.log, np.sqrt, np.sum, etc.)
2. Assume 'import numpy as np' is available
3. Variables should be plain Python identifiers
4. The python_code must be a valid Python expression (not a statement)
5. Do NOT include import statements in python_code"""


def clean_latex(latex: str) -> str:
    r"""Strip LaTeX macros unsupported by SymPy's parse_latex.

    Handles: annotations (\tag, \label), text/formatting commands,
    spacing, delimiters (\left/\right), equivalence symbols, dots,
    style commands, and alignment markers.
    """
    s = latex
    # 1. Remove \tag{...}, \label{...} (non-math annotations)
    s = re.sub(r'\\tag\{[^}]*\}', '', s)
    s = re.sub(r'\\label\{[^}]*\}', '', s)
    # 2. Unwrap text/formatting commands: \text{foo} → foo
    for cmd in ('text', 'textit', 'textbf', 'textrm', 'mathrm', 'mathbf',
                'mathbb', 'mathcal', 'mathfrak', 'boldsymbol', 'pmb',
                'operatorname', 'bm'):
        s = re.sub(r'\\' + cmd + r'\{([^{}]*(?:\{[^{}]*\}[^{}]*)*)\}',
                   r'\1', s)
    # 3. Remove spacing commands
    s = re.sub(r'\\[,;:!]', '', s)
    s = re.sub(r'\\(?:quad|qquad|hspace\{[^}]*\}|vspace\{[^}]*\})', '', s)
    # 4. Remove \left, \right (SymPy handles parens natively)
    s = re.sub(r'\\(?:left|right)\s*[.|\[\](){}\\|]?', '', s)
    # 5. Replace equivalence symbols with =
    for equiv in (r'\equiv', r'\triangleq', r'\coloneqq', r'\defeq'):
        s = s.replace(equiv, '=')
    # 6. Remove dots
    s = re.sub(r'\\[lcvd]?dots', '', s)
    s = s.replace(r'\cdots', '')
    # 7. Remove style commands
    s = re.sub(r'\\(?:display|text|script|scriptscript)style', '', s)
    # 7b. Remove sizing commands: \big, \Big, \bigg, \Bigg (and l/r variants)
    s = re.sub(r'\\[Bb]ig{1,2}[lrm]?', '', s)
    # 7c. Replace \parallel, \| with comma (KL divergence notation)
    s = s.replace(r'\parallel', ',')
    s = re.sub(r'(?<!\\)\\\|', ',', s)
    # 7d. Normalize sign subscripts: _{-} → _{minus}, ^{+} → ^{plus}
    s = s.replace('_{-}', '_{minus}').replace('^{+}', '^{plus}')
    s = s.replace('_{+}', '_{plus}').replace('^{-}', '^{minus}')
    # 8. Remove \nonumber, \notag, line breaks, alignment
    s = s.replace(r'\nonumber', '').replace(r'\notag', '')
    s = re.sub(r'\\\\', ' ', s)
    s = s.replace('&', ' ')
    # 9. Collapse whitespace
    s = re.sub(r'\s+', ' ', s).strip()
    return s


def _split_multiline(latex: str) -> str:
    r"""Extract a single equation from multi-line LaTeX.

    Layer 2: Handles \\-separated lines (align environments), \Rightarrow
    prefixes, and equality chains (a = b = c → a = c).

    Args:
        latex: LaTeX string (environments already stripped).

    Returns:
        Single equation string suitable for parse_latex.
    """
    # Split on literal \\ (line breaks in align/gather environments)
    if r'\\' in latex:
        lines = [l.strip() for l in re.split(r'\\\\', latex) if l.strip()]
        if lines:
            latex = lines[-1]  # take last equation (usually the result)

    # Remove \Rightarrow prefix (e.g. "⟹ y = f(x)")
    latex = re.sub(r'^\\Rightarrow\s*', '', latex).strip()

    # Equality chain: a = b = c → a = c (keep first and last parts)
    parts = re.split(r'\s*=\s*', latex)
    if len(parts) > 2:
        latex = f"{parts[0]} = {parts[-1]}"

    return latex


def parse_formula(latex: str) -> sympy.Expr:
    """Parse LaTeX to SymPy expression.

    Uses ANTLR backend (default, more lenient).
    Strips environment wrappers, math delimiters, and unsupported macros.
    Layer 2: Splits multi-line equations and handles equality chains.

    Args:
        latex: LaTeX formula string.

    Returns:
        SymPy expression.

    Raises:
        Exception: If parsing fails (SyntaxError, etc.).
    """
    # Strip LaTeX environments
    cleaned = re.sub(r'\\begin\{[^}]+\}|\\end\{[^}]+\}', '', latex).strip()
    # Strip display math delimiters
    cleaned = re.sub(r'^\$\$|^\$|\$\$$|\$$', '', cleaned).strip()
    # Layer 2: Multi-line split before macro cleanup
    cleaned = _split_multiline(cleaned)
    # Strip unsupported macros
    cleaned = clean_latex(cleaned)
    if not cleaned:
        raise ValueError("Empty LaTeX after cleanup")
    return parse_latex(cleaned)  # type: ignore[return-value]


def _llm_codegen_python(latex: str, func_name: str) -> dict | None:
    """Layer 5: LLM fallback for Python codegen when parse_latex fails.

    Calls the LLM fallback chain to convert LaTeX → Python/numpy code.
    Returns None if all providers fail or validation fails.

    Args:
        latex: Raw LaTeX formula string.
        func_name: Function name for metadata.

    Returns:
        Dict with keys python_code, variables, provider — or None on failure.
    """
    from shared.llm import fallback_chain

    prompt = f"Convert this LaTeX formula to Python/numpy code:\n\n{latex}"
    try:
        raw, provider = fallback_chain(
            prompt=prompt,
            system=_LLM_CODEGEN_SYSTEM,
            order=CODEGEN_FALLBACK_ORDER,
        )
        result = LLMCodegenResult.model_validate_json(raw)
        return {
            "python_code": result.python_code,
            "variables": result.variables,
            "description": result.description,
            "provider": provider,
        }
    except Exception as e:
        logger.warning("LLM codegen fallback failed for %s: %s", func_name, e)
        return None


def generate_c99(expr: sympy.Expr, func_name: str) -> dict:
    """Generate complete C99 function via SymPy codegen.

    Args:
        expr: SymPy expression to generate code for.
        func_name: Name for the generated function.

    Returns:
        {"code": str, "header": str, "variables": list[str]}
    """
    variables = sorted(expr.free_symbols, key=str)
    result = codegen(
        (func_name, expr), "C99", func_name, header=False, empty=False
    )
    # codegen returns [(c_name, c_code), (h_name, h_code)]
    c_code = result[0][1]
    c_header = result[1][1] if len(result) > 1 else ""
    return {
        "code": c_code,
        "header": c_header,
        "variables": [str(v) for v in variables],
    }


def generate_rust(expr: sympy.Expr, func_name: str) -> dict:
    """Generate Rust function via SymPy codegen.

    Known issue: integer literals may not be promoted to f64 (#26967).

    Args:
        expr: SymPy expression to generate code for.
        func_name: Name for the generated function.

    Returns:
        {"code": str, "variables": list[str]}
    """
    variables = sorted(expr.free_symbols, key=str)
    result = codegen(
        (func_name, expr), "Rust", func_name, header=False, empty=False
    )
    rs_code = result[0][1]
    return {
        "code": rs_code,
        "variables": [str(v) for v in variables],
    }


def generate_python(expr: sympy.Expr, func_name: str) -> str:
    """Generate Python expression via pycode().

    Layer 4: Falls back to strict=False when Function objects are not
    printable (e.g. custom or unrecognized SymPy functions).

    Args:
        expr: SymPy expression to generate code for.
        func_name: Name for the generated function (unused, for API consistency).

    Returns:
        Python code string.
    """
    try:
        return pycode(expr)  # type: ignore[return-value]
    except Exception:
        return pycode(expr, strict=False)  # type: ignore[return-value]


def generate_all(latex: str, formula_id: int) -> list[dict]:
    """Generate code in all 3 languages for a formula.

    Per-language error isolation: if C99 fails, Rust and Python still proceed.

    Args:
        latex: LaTeX formula string.
        formula_id: Formula ID for function naming.

    Returns:
        List of {language, code, metadata, error} dicts.
    """
    func_name = f"formula_{formula_id}"

    try:
        expr = parse_formula(latex)
    except Exception as e:
        logger.warning("parse_latex failed for formula %d: %s", formula_id, e)
        # Layer 5: LLM fallback for Python-only when parse_latex fails
        llm_result = _llm_codegen_python(latex, func_name)
        if llm_result is not None:
            return [
                {"language": "c99", "code": "", "metadata": None,
                 "error": f"parse_latex: {e}"},
                {"language": "rust", "code": "", "metadata": None,
                 "error": f"parse_latex: {e}"},
                {"language": "python", "code": llm_result["python_code"],
                 "metadata": {
                     "function_name": func_name,
                     "variables": llm_result.get("variables", []),
                     "source": "llm",
                     "llm_provider": llm_result.get("provider", "unknown"),
                 },
                 "error": None},
            ]
        return [
            {"language": lang, "code": "", "metadata": None,
             "error": f"parse_latex: {e}"}
            for lang in ("c99", "rust", "python")
        ]

    # Layer 3: Equality.rhs extraction — codegen can't handle Equality objects
    if isinstance(expr, sympy.Equality):
        expr = expr.rhs

    results = []

    for lang, gen_func in [("c99", generate_c99), ("rust", generate_rust)]:
        try:
            result = gen_func(expr, func_name)
            results.append({
                "language": lang,
                "code": result["code"],
                "metadata": {
                    "function_name": func_name,
                    "variables": result["variables"],
                },
                "error": None,
            })
        except Exception as e:
            logger.warning("generate_%s failed for formula %d: %s",
                           lang, formula_id, e)
            results.append({
                "language": lang,
                "code": "",
                "metadata": None,
                "error": str(e),
            })

    # Python via pycode
    try:
        py_code = generate_python(expr, func_name)
        results.append({
            "language": "python",
            "code": py_code,
            "metadata": {
                "function_name": func_name,
                "variables": [str(s) for s in sorted(
                    expr.free_symbols, key=str
                )],
            },
            "error": None,
        })
    except Exception as e:
        logger.warning("generate_python failed for formula %d: %s",
                       formula_id, e)
        results.append({
            "language": "python",
            "code": "",
            "metadata": None,
            "error": str(e),
        })

    return results
