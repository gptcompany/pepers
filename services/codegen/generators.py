"""SymPy-based code generation for validated formulas.

Transforms LaTeX strings into executable code in three languages:
- C99 (primary) via codegen("C99")
- Rust (secondary) via codegen("Rust")
- Python (always) via pycode()

Uses SymPy's parse_latex (ANTLR backend) for LaTeX→Expr conversion.
Per-language error isolation: one failure doesn't block others.
"""

from __future__ import annotations

import logging
import re

import sympy
from sympy.parsing.latex import parse_latex
from sympy.printing.pycode import pycode
from sympy.utilities.codegen import codegen

logger = logging.getLogger(__name__)


def parse_formula(latex: str) -> sympy.Expr:
    """Parse LaTeX to SymPy expression.

    Uses ANTLR backend (default, more lenient).
    Strips environment wrappers (\\begin{equation}...\\end{equation}).

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
    if not cleaned:
        raise ValueError("Empty LaTeX after cleanup")
    return parse_latex(cleaned)  # type: ignore[return-value]


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

    Args:
        expr: SymPy expression to generate code for.
        func_name: Name for the generated function (unused, for API consistency).

    Returns:
        Python code string.
    """
    return pycode(expr)  # type: ignore[return-value]


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
        return [
            {"language": lang, "code": "", "metadata": None,
             "error": f"parse_latex: {e}"}
            for lang in ("c99", "rust", "python")
        ]

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
