"""GitHub repository search and analysis via Gemini CLI.

Searches GitHub for implementations related to academic papers,
clones promising repos, and analyzes them using Gemini CLI with
``--include-directories`` for native file access (1M context).

Falls back to Gemini SDK with file contents in prompt when CLI
is unavailable (e.g. inside Docker containers).
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path

logger = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com/search/repositories"


def search_github(query: str, max_results: int = 10) -> list[dict]:
    """Search GitHub repositories via REST API.

    Filters: Python repos, sorted by stars.
    Returns list of dicts with repo metadata.
    """
    params = urllib.parse.urlencode({
        "q": f"{query} language:python",
        "sort": "stars",
        "per_page": min(max_results, 30),
    })
    req = urllib.request.Request(
        f"{GITHUB_API}?{params}",
        headers={"Accept": "application/vnd.github.v3+json"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read())

    return [
        {
            "name": r["name"],
            "full_name": r["full_name"],
            "url": r["html_url"],
            "clone_url": r["clone_url"],
            "description": r.get("description", ""),
            "stars": r["stargazers_count"],
            "language": r.get("language"),
            "updated_at": r["updated_at"],
        }
        for r in data.get("items", [])
    ]


def clone_repo(clone_url: str) -> Path:
    """Shallow-clone a repo to a temp directory. Returns clone path."""
    tmp_dir = Path(tempfile.mkdtemp(prefix="research-github-"))
    subprocess.run(
        [
            "git", "clone", "--depth", "1", "--quiet",
            clone_url, str(tmp_dir / "repo"),
        ],
        timeout=60,
        check=True,
        capture_output=True,
    )
    return tmp_dir / "repo"


def cleanup_clone(clone_path: Path) -> None:
    """Remove a cloned repo created by :func:`clone_repo`."""
    parent = clone_path.parent
    if str(parent).startswith("/tmp/research-github-"):
        shutil.rmtree(parent, ignore_errors=True)


def build_dynamic_prompt(paper_context: dict, repo_info: dict) -> str:
    """Build an analysis prompt from paper context and repo info.

    Args:
        paper_context: Paper dict from ``GET /papers?id=N`` (with
            nested ``formulas``).
        repo_info: Dict from :func:`search_github`.
    """
    formulas = paper_context.get("formulas", [])
    formula_section = ""
    if formulas:
        lines = []
        for f in formulas[:15]:
            desc = f.get("description") or "no description"
            lines.append(f"- `${f['latex']}$` ({desc})")
        formula_section = "**Key Formulas:**\n" + "\n".join(lines)

    return (
        "You are analyzing a GitHub repository for relevance to an "
        "academic paper.\n\n"
        "## Paper Context\n"
        f"**Title**: {paper_context.get('title', 'Unknown')}\n"
        f"**Abstract**: {(paper_context.get('abstract') or '')[:800]}\n"
        f"**Stage**: {paper_context.get('stage', 'unknown')}\n"
        f"{formula_section}\n\n"
        "## Repository\n"
        f"**Name**: {repo_info.get('full_name', 'Unknown')}\n"
        f"**Description**: {repo_info.get('description', 'N/A')}\n"
        f"**Stars**: {repo_info.get('stars', 0)}\n\n"
        "## Analysis Tasks\n"
        "1. **Formula Match**: Does this repo implement any of the "
        "formulas above? Map specific code files/functions to specific "
        "formulas.\n"
        "2. **Algorithm Quality**: Is the implementation mathematically "
        "correct? Check edge cases (division by zero, boundary "
        "conditions).\n"
        "3. **Code Maturity**: Test coverage, type hints, error "
        "handling, documentation.\n"
        "4. **Dependencies**: Key Python dependencies and version "
        "requirements.\n"
        "5. **Usability**: Can this be imported as a library or is it a "
        "standalone script?\n\n"
        "## Output\n"
        "Return a JSON object with exactly these fields:\n"
        "{\n"
        '  "relevance_score": <0-100>,\n'
        '  "formula_matches": [\n'
        '    {"formula_latex": "...", "code_file": "...", '
        '"function_name": "...", '
        '"match_quality": "exact|approximate|inspired"}\n'
        "  ],\n"
        '  "quality_score": <0-100>,\n'
        '  "summary": "<2-3 sentences>",\n'
        '  "key_files": ["<most relevant files>"],\n'
        '  "dependencies": ["<key deps>"],\n'
        '  "recommendation": "USE|REFERENCE|SKIP"\n'
        "}"
    )


def analyze_with_gemini_cli(
    clone_path: Path,
    prompt: str,
    model: str | None = None,
    timeout: int = 180,
) -> dict:
    """Analyze a cloned repo with Gemini CLI.

    Tries Gemini CLI with ``--include-directories`` first (native file
    access, 1M context).  Falls back to Gemini SDK with file contents
    concatenated into the prompt.
    """
    model = model or os.environ.get(
        "RP_GITHUB_ANALYSIS_MODEL", "gemini-2.5-pro"
    )

    try:
        result = subprocess.run(
            [
                "gemini", "-p", prompt,
                "--include-directories", str(clone_path),
                "-m", model,
                "--approval-mode", "yolo",
                "-o", "json",
                "-e", "none",
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
            stdin=subprocess.DEVNULL,
        )
        if result.returncode == 0:
            data = json.loads(result.stdout)
            response = data.get("response", "")
            return _parse_json_response(response)
    except (
        FileNotFoundError,
        subprocess.TimeoutExpired,
        json.JSONDecodeError,
    ) as exc:
        logger.warning("Gemini CLI failed, trying SDK fallback: %s", exc)

    return _analyze_with_sdk_fallback(clone_path, prompt, model)


def _parse_json_response(text: str) -> dict:
    """Extract JSON from a response that may contain markdown fences."""
    text = text.strip()
    # Strip ```json ... ``` fences
    if text.startswith("```"):
        first_nl = text.index("\n")
        text = text[first_nl + 1 :]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
    return json.loads(text)


def _analyze_with_sdk_fallback(
    clone_path: Path, prompt: str, model: str
) -> dict:
    """SDK fallback: read Python files and include in prompt."""
    files_content = _read_repo_files(clone_path)
    full_prompt = (
        f"{prompt}\n\n## Repository Source Code\n\n{files_content}"
    )

    from shared.llm import call_gemini_sdk

    response = call_gemini_sdk(full_prompt, system="", model=model)
    return _parse_json_response(response)


def _read_repo_files(
    repo_path: Path, max_chars: int = 400_000
) -> str:
    """Read Python files from a repo, formatted as markdown code blocks."""
    skip_dirs = {"venv", ".venv", "node_modules", "__pycache__", ".git"}
    content_parts: list[str] = []
    total = 0

    for py_file in sorted(repo_path.rglob("*.py")):
        if skip_dirs & set(py_file.parts):
            continue
        try:
            text = py_file.read_text(errors="replace")
            rel = py_file.relative_to(repo_path)
            part = f"### {rel}\n```python\n{text}\n```\n"
            if total + len(part) > max_chars:
                break
            content_parts.append(part)
            total += len(part)
        except OSError:
            continue

    return "\n".join(content_parts)


def search_and_analyze(
    query: str,
    paper_context: dict | None = None,
    prompt_override: str | None = None,
    max_repos: int = 3,
) -> dict:
    """Full flow: search GitHub, clone, analyze, cleanup.

    Args:
        query: Search query for GitHub.
        paper_context: Paper dict from pipeline (optional).
        prompt_override: Skill-generated dynamic prompt (overrides
            auto-generated prompt from paper_context).
        max_repos: Max repos to clone and analyze.

    Returns:
        Dict with ``repos_found``, ``repos_analyzed``, and ``results``.
    """
    repos = search_github(query, max_results=max_repos * 3)

    results: list[dict] = []
    for repo in repos[:max_repos]:
        clone_path = None
        try:
            clone_path = clone_repo(repo["clone_url"])

            if prompt_override:
                prompt = prompt_override
            elif paper_context:
                prompt = build_dynamic_prompt(paper_context, repo)
            else:
                prompt = (
                    f"Analyze this repository for: {query}. "
                    "Return JSON with relevance_score, quality_score, "
                    "summary, recommendation."
                )

            analysis = analyze_with_gemini_cli(clone_path, prompt)
            results.append({"repo": repo, "analysis": analysis})
        except Exception as exc:
            logger.error(
                "Failed to analyze %s: %s", repo["full_name"], exc,
            )
            results.append({
                "repo": repo,
                "analysis": {"error": str(exc), "recommendation": "SKIP"},
            })
        finally:
            if clone_path:
                cleanup_clone(clone_path)

    return {
        "repos_found": len(repos),
        "repos_analyzed": len(results),
        "results": results,
    }
