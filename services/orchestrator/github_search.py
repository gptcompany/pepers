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
import re
import shutil
import subprocess
import tempfile
import time
import urllib.parse
import urllib.request
from pathlib import Path

logger = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com/search/repositories"

# File extensions to read for SDK fallback analysis
EXTENSIONS = {"*.py", "*.rs", "*.cpp", "*.hpp", "*.c", "*.h"}
SKIP_DIRS = {
    "venv", ".venv", "node_modules", "__pycache__", ".git",
    "target", "build", "dist", ".tox", "vendor",
}

# Academic stop words removed from title when generating search queries
STOP_WORDS = {
    "a", "an", "the", "of", "for", "in", "on", "to", "and", "or",
    "with", "by", "from", "is", "are", "was", "were", "be", "been",
    "being", "that", "this", "which", "as", "at", "it", "its",
    "optimal", "analysis", "study", "approach", "method", "methods",
    "new", "novel", "based", "using", "via", "towards", "toward",
    "under", "over", "between", "through", "into",
}


def _get_github_headers() -> dict[str, str]:
    """Build GitHub API headers with PAT authentication."""
    pat = os.environ.get("RP_GITHUB_PAT", "") or os.environ.get("GITHUB_PAT", "")
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if pat:
        headers["Authorization"] = f"Bearer {pat}"
    return headers


def _check_rate_limit(resp_headers: dict) -> None:
    """Sleep if GitHub rate limit is nearly exhausted."""
    remaining = int(resp_headers.get("x-ratelimit-remaining", "30"))
    reset_at = int(resp_headers.get("x-ratelimit-reset", "0"))
    if remaining < 2 and reset_at > 0:
        sleep_until = reset_at - time.time()
        if sleep_until > 0:
            logger.info("GitHub rate limit low (%d), sleeping %.0fs", remaining, sleep_until + 1)
            time.sleep(sleep_until + 1)


def _extract_keywords(title: str) -> list[str]:
    """Extract domain-specific keywords from paper title."""
    words = re.findall(r"[A-Za-z]+(?:[-'][A-Za-z]+)*", title)
    keywords = [w for w in words if w.lower() not in STOP_WORDS and len(w) > 2]
    return keywords[:5]


def search_github(
    query: str,
    *,
    languages: list[str] | None = None,
    min_stars: int = 5,
    max_results: int = 30,
) -> list[dict]:
    """Search GitHub repositories via REST API with multi-language support.

    Builds per-language queries, merges and deduplicates by full_name,
    sorts by stars descending.

    Args:
        query: Base search query (paper keywords).
        languages: List of languages to search. Defaults to config.
        min_stars: Minimum star count filter.
        max_results: Max total results across all languages.

    Returns:
        List of repo dicts sorted by stars.
    """
    if languages is None:
        lang_str = os.environ.get("RP_GITHUB_LANGUAGES", "python,rust,cpp")
        languages = [lang.strip() for lang in lang_str.split(",")]

    headers = _get_github_headers()
    all_repos: dict[str, dict] = {}

    for lang in languages:
        lang_query = f"{query} language:{lang} stars:>{min_stars} pushed:>2024-01-01 archived:false"
        params = urllib.parse.urlencode({
            "q": lang_query,
            "sort": "stars",
            "per_page": min(max_results, 30),
        })

        req = urllib.request.Request(
            f"{GITHUB_API}?{params}",
            headers=headers,
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                _check_rate_limit(dict(resp.headers))
                data = json.loads(resp.read())
        except urllib.error.HTTPError as e:
            if e.code == 403:
                logger.warning("GitHub rate limited for lang=%s, skipping", lang)
                _check_rate_limit(dict(e.headers))
                continue
            raise

        for r in data.get("items", []):
            full_name = r["full_name"]
            if full_name not in all_repos:
                all_repos[full_name] = {
                    "full_name": full_name,
                    "url": r["html_url"],
                    "clone_url": r["clone_url"],
                    "description": r.get("description", ""),
                    "stars": r["stargazers_count"],
                    "language": r.get("language"),
                    "updated_at": r.get("updated_at"),
                    "topics": r.get("topics", []),
                }

    sorted_repos = sorted(all_repos.values(), key=lambda r: r["stars"], reverse=True)
    return sorted_repos[:max_results]


def clone_repo(clone_url: str, timeout: int | None = None) -> Path:
    """Shallow-clone a repo to a temp directory.

    Args:
        clone_url: Git clone URL.
        timeout: Clone timeout in seconds. Defaults to RP_GITHUB_CLONE_TIMEOUT.

    Returns:
        Path to cloned repo directory.
    """
    if timeout is None:
        timeout = int(os.environ.get("RP_GITHUB_CLONE_TIMEOUT", "60"))

    tmp_dir = Path(tempfile.mkdtemp(prefix="research-github-"))
    subprocess.run(
        [
            "git", "clone", "--depth", "1", "--quiet",
            clone_url, str(tmp_dir / "repo"),
        ],
        timeout=timeout,
        check=True,
        capture_output=True,
    )
    return tmp_dir / "repo"


def cleanup_clone(clone_path: Path) -> None:
    """Remove a cloned repo created by :func:`clone_repo`."""
    parent = clone_path.parent
    if str(parent).startswith(tempfile.gettempdir()):
        shutil.rmtree(parent, ignore_errors=True)


def build_dynamic_prompt(paper_context: dict, repo_info: dict) -> str:
    """Build an analysis prompt from paper context and repo info.

    Args:
        paper_context: Paper dict with nested ``formulas``.
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

    repo_lang = repo_info.get("language", "Unknown")

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
        f"**Stars**: {repo_info.get('stars', 0)}\n"
        f"**Primary Language**: {repo_lang}\n\n"
        "## Analysis Tasks\n"
        "1. **Formula Match**: Does this repo implement any of the "
        "formulas above? Map specific code files/functions to specific "
        "formulas. Include variable mappings (paper variable → code variable).\n"
        "2. **Algorithm Quality**: Is the implementation mathematically "
        "correct? Check edge cases (division by zero, boundary "
        "conditions).\n"
        "3. **Code Maturity**: Test coverage, type hints, error "
        "handling, documentation.\n"
        f"4. **Dependencies**: Key {repo_lang} dependencies and version "
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
    timeout: int | None = None,
) -> dict:
    """Analyze a cloned repo with Gemini CLI.

    Tries Gemini CLI with ``--include-directories`` first (native file
    access, 1M context).  Falls back to Gemini SDK with file contents
    concatenated into the prompt.

    Args:
        clone_path: Path to cloned repository.
        prompt: Analysis prompt text.
        model: Gemini model name. Defaults to RP_GITHUB_ANALYSIS_MODEL.
        timeout: Analysis timeout. Defaults to RP_GITHUB_ANALYSIS_TIMEOUT.

    Returns:
        Parsed analysis dict with scores and recommendations.
    """
    if model is None:
        model = os.environ.get("RP_GITHUB_ANALYSIS_MODEL", "gemini-2.5-pro")
    if timeout is None:
        timeout = int(os.environ.get("RP_GITHUB_ANALYSIS_TIMEOUT", "180"))

    try:
        result = subprocess.run(
            [
                "gemini", prompt,
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
        text = text[first_nl + 1:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
    return json.loads(text)


def _analyze_with_sdk_fallback(
    clone_path: Path, prompt: str, model: str
) -> dict:
    """SDK fallback: read source files and include in prompt."""
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
    """Read source files from a repo, formatted as markdown code blocks.

    Supports Python, Rust, C, and C++ files.
    """
    ext_to_lang = {
        ".py": "python", ".rs": "rust",
        ".cpp": "cpp", ".hpp": "cpp",
        ".c": "c", ".h": "c",
    }
    content_parts: list[str] = []
    total = 0

    for src_file in sorted(repo_path.rglob("*")):
        if not src_file.is_file():
            continue
        if src_file.suffix not in ext_to_lang:
            continue
        if SKIP_DIRS & set(src_file.parts):
            continue
        try:
            text = src_file.read_text(errors="replace")
            rel = src_file.relative_to(repo_path)
            lang = ext_to_lang[src_file.suffix]
            part = f"### {rel}\n```{lang}\n{text}\n```\n"
            if total + len(part) > max_chars:
                break
            content_parts.append(part)
            total += len(part)
        except OSError:
            continue

    return "\n".join(content_parts)


def _store_repo(conn, paper_id: int, repo: dict, search_query: str) -> int:
    """Insert or update a GitHub repo in the database.

    Returns:
        The repo row ID.
    """
    topics_json = json.dumps(repo.get("topics", []))
    conn.execute(
        """INSERT OR IGNORE INTO github_repos
           (paper_id, full_name, url, clone_url, description,
            stars, language, updated_at, topics, search_query)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            paper_id,
            repo["full_name"],
            repo["url"],
            repo["clone_url"],
            repo.get("description", ""),
            repo.get("stars", 0),
            repo.get("language"),
            repo.get("updated_at"),
            topics_json,
            search_query,
        ),
    )
    row = conn.execute(
        "SELECT id FROM github_repos WHERE paper_id = ? AND full_name = ?",
        (paper_id, repo["full_name"]),
    ).fetchone()
    return row["id"]


def _store_analysis(conn, repo_id: int, analysis: dict, model_used: str,
                    time_ms: int) -> int:
    """Insert a Gemini analysis result in the database.

    Returns:
        The analysis row ID.
    """
    cursor = conn.execute(
        """INSERT INTO github_analyses
           (repo_id, relevance_score, quality_score, formula_matches,
            summary, recommendation, key_files, dependencies,
            model_used, analysis_time_ms, error)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            repo_id,
            analysis.get("relevance_score"),
            analysis.get("quality_score"),
            json.dumps(analysis.get("formula_matches", [])),
            analysis.get("summary"),
            analysis.get("recommendation"),
            json.dumps(analysis.get("key_files", [])),
            json.dumps(analysis.get("dependencies", [])),
            model_used,
            time_ms,
            analysis.get("error"),
        ),
    )
    return cursor.lastrowid


def _load_paper_context(conn, paper_id: int) -> dict | None:
    """Load paper with formulas from DB for prompt generation."""
    row = conn.execute(
        "SELECT * FROM papers WHERE id = ?", (paper_id,)
    ).fetchone()
    if row is None:
        return None

    paper = dict(row)

    f_rows = conn.execute(
        "SELECT * FROM formulas WHERE paper_id = ? ORDER BY id",
        (paper_id,),
    ).fetchall()
    paper["formulas"] = [dict(fr) for fr in f_rows]

    return paper


def _generate_queries(paper_context: dict) -> list[str]:
    """Generate search queries from paper title and abstract."""
    title = paper_context.get("title", "")
    keywords = _extract_keywords(title)

    queries = []
    # Primary: quoted title keywords
    if len(keywords) >= 2:
        quoted = " ".join(keywords[:4])
        queries.append(f'"{quoted}"')

    # Fallback: keywords in readme
    if keywords:
        fallback = " ".join(keywords[:5]) + " in:readme"
        queries.append(fallback)

    return queries or [title[:80]]


def search_and_analyze(
    paper_id: int,
    db_path: str,
    *,
    max_repos: int | None = None,
    languages: list[str] | None = None,
    min_stars: int | None = None,
    query_override: str | None = None,
    force: bool = False,
) -> dict:
    """Full flow: load paper, search GitHub, clone, analyze, store, cleanup.

    Args:
        paper_id: Paper ID to find implementations for.
        db_path: Path to SQLite database.
        max_repos: Max repos to analyze. Defaults to RP_GITHUB_MAX_REPOS.
        languages: Languages to search. Defaults to config.
        min_stars: Minimum stars. Defaults to RP_GITHUB_MIN_STARS.
        query_override: Override auto-generated search query.
        force: Re-analyze even if results exist.

    Returns:
        Dict with repos_found, repos_analyzed, results, errors.
    """
    from shared.db import transaction

    if max_repos is None:
        max_repos = int(os.environ.get("RP_GITHUB_MAX_REPOS", "3"))
    if min_stars is None:
        min_stars = int(os.environ.get("RP_GITHUB_MIN_STARS", "5"))

    gemini_rpm = int(os.environ.get("RP_GITHUB_GEMINI_RPM", "5"))
    sleep_between = 60.0 / gemini_rpm
    model = os.environ.get("RP_GITHUB_ANALYSIS_MODEL", "gemini-2.5-pro")
    max_repo_size = int(os.environ.get("RP_GITHUB_MAX_REPO_SIZE", "500000"))

    # Load paper context
    with transaction(db_path) as conn:
        paper_context = _load_paper_context(conn, paper_id)

    if paper_context is None:
        return {
            "paper_id": paper_id,
            "repos_found": 0,
            "repos_analyzed": 0,
            "results": [],
            "errors": [f"Paper {paper_id} not found"],
        }

    # Check for existing results (skip if not force)
    if not force:
        with transaction(db_path) as conn:
            existing = conn.execute(
                "SELECT COUNT(*) as cnt FROM github_repos WHERE paper_id = ?",
                (paper_id,),
            ).fetchone()
            if existing["cnt"] > 0:
                return {
                    "paper_id": paper_id,
                    "repos_found": existing["cnt"],
                    "repos_analyzed": existing["cnt"],
                    "results": [],
                    "errors": [],
                    "skipped": True,
                    "reason": "Results already exist. Use force=true to re-analyze.",
                }

    # Generate or use override query
    if query_override:
        queries = [query_override]
    else:
        queries = _generate_queries(paper_context)

    # Search GitHub (try each query, merge results)
    all_repos: dict[str, dict] = {}
    search_query_used = ""
    for query in queries:
        repos = search_github(
            query,
            languages=languages,
            min_stars=min_stars,
            max_results=max_repos * 3,
        )
        for repo in repos:
            if repo["full_name"] not in all_repos:
                all_repos[repo["full_name"]] = repo
                if not search_query_used:
                    search_query_used = query

        if len(all_repos) >= max_repos:
            break

    sorted_repos = sorted(all_repos.values(), key=lambda r: r["stars"], reverse=True)
    top_repos = sorted_repos[:max_repos]

    # Analyze each repo
    results: list[dict] = []
    errors: list[str] = []

    for i, repo in enumerate(top_repos):
        clone_path = None
        try:
            # Skip oversized repos
            size_kb = repo.get("size", 0)
            if size_kb > max_repo_size:
                logger.warning(
                    "Skipping %s: size %d KB > max %d KB",
                    repo["full_name"], size_kb, max_repo_size,
                )
                errors.append(f"{repo['full_name']}: too large ({size_kb} KB)")
                continue

            clone_path = clone_repo(repo["clone_url"])
            prompt = build_dynamic_prompt(paper_context, repo)

            start_ms = time.time()
            analysis = analyze_with_gemini_cli(clone_path, prompt, model=model)
            elapsed_ms = int((time.time() - start_ms) * 1000)

            # Store in DB
            with transaction(db_path) as conn:
                repo_id = _store_repo(conn, paper_id, repo, search_query_used)
                analysis_id = _store_analysis(conn, repo_id, analysis, model, elapsed_ms)

            results.append({
                "repo": {**repo, "id": repo_id, "paper_id": paper_id},
                "analysis": {**analysis, "id": analysis_id, "repo_id": repo_id,
                             "model_used": model, "analysis_time_ms": elapsed_ms},
            })

        except Exception as exc:
            logger.error("Failed to analyze %s: %s", repo["full_name"], exc)
            error_msg = f"{repo['full_name']}: {exc}"
            errors.append(error_msg)

            # Store error in DB
            try:
                with transaction(db_path) as conn:
                    repo_id = _store_repo(conn, paper_id, repo, search_query_used)
                    _store_analysis(conn, repo_id,
                                    {"error": str(exc), "recommendation": "SKIP"},
                                    model, 0)
            except Exception:
                logger.exception("Failed to store error for %s", repo["full_name"])

        finally:
            if clone_path:
                cleanup_clone(clone_path)

            # Rate limit between analyses (skip after last)
            if i < len(top_repos) - 1:
                logger.debug("Sleeping %.1fs between analyses", sleep_between)
                time.sleep(sleep_between)

    return {
        "paper_id": paper_id,
        "repos_found": len(all_repos),
        "repos_analyzed": len(results),
        "results": results,
        "errors": errors,
    }
