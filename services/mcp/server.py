"""PePeRS MCP Server — Model Context Protocol interface for the pipeline.

Thin wrapper that translates MCP tool calls into HTTP requests to the
orchestrator service (:8775). Uses the official Python MCP SDK with SSE
transport.

Usage:
    python -m services.mcp

Environment:
    RP_MCP_PORT=8776                  # SSE server port (default: 8776)
    RP_ORCHESTRATOR_URL=http://localhost:8775  # Orchestrator base URL
    RP_MCP_FLAVOR=arcade              # Output flavor: arcade|plain
"""

from __future__ import annotations

import json
import logging
import os
import random
import urllib.request
import urllib.error

from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)

# -- Configuration --

ORCHESTRATOR_URL = os.environ.get(
    "RP_ORCHESTRATOR_URL", "http://localhost:8775"
)
MCP_FLAVOR = os.environ.get("RP_MCP_FLAVOR", "arcade")

# -- ARCADE+PEPE flavor (Metal Slug × degen frog) --

ARCADE_MESSAGES: dict[str, list[str]] = {
    "search_found": [
        "🔫 HEAVY MACHINE GUN! {n} papers acquired, fren. LFG! 🐸💎",
        "💎 {n} papers locked and loaded! Diamond hands on this intel, ser! 🐸🔫",
        "🚀 COMBO x{n}! Papers acquired. We're so early, fren! 🐸",
    ],
    "search_empty": [
        "💀 NOTHING HERE... Radar empty, ser. Touch grass and retry! 🐸",
        "🐸 Zero hits, fren. The alpha is hiding. Try different keywords! 💀",
        "😤 NO SIGNAL! Papers are playing dead. ngmi with this query! 🐸",
    ],
    "search_context": [
        "🎯 SHOTGUN! {n} context chunks extracted. Intel is based! 🐸🚀",
        "💎 {n} chunks of pure alpha extracted! Knowledge goes brrr! 🐸🎯",
        "🔫 LASER GUN! {n} context fragments locked. based intel, ser! 🐸",
    ],
    "list_papers": [
        "🚀 ROCKET LAUNCHER! {n} papers loaded in arsenal. wagmi! 🐸",
        "🐸 {n} papers in the bag! That's a full magazine, ser! 💎🚀",
        "💥 ARSENAL CHECK! {n} papers armed and ready. LFG! 🐸",
    ],
    "get_paper": [
        "🐸 ENEMY CHASER! Paper #{id} dossier retrieved. based intel, ser!",
        "💎 Paper #{id} acquired! Dossier is fire, fren! 🐸🔥",
        "🎯 BULLSEYE! Paper #{id} locked. This is the way, ser! 🐸",
    ],
    "get_paper_notfound": [
        "😤 PRISONER NOT FOUND! Paper #{id} is MIA. ngmi! 🐸",
        "💀 Paper #{id} rugged us, ser. It's gone! 🐸",
        "🐸 Paper #{id}? Never heard of her, fren. ngmi! 😤",
    ],
    "formulas_found": [
        "💎 IRON LIZARD! {n} formulas decoded. Math goes brrr! 🐸🔥",
        "🔥 {n} formulas extracted! Pure math alpha, ser! 🐸💎",
        "🚀 SUPER SHELL! {n} formulas cracked. We're all gonna make it! 🐸",
    ],
    "formulas_empty": [
        "📭 EMPTY MAGAZINE! No formulas found. wen formulas, ser? 🐸",
        "🐸 Zero formulas, fren. The math is hiding. wen extraction? 📭",
        "💀 NO FORMULAS! Paper needs more cooking, ser! 🐸",
    ],
    "run_start": [
        "🚀 MISSION {id} START! GO GO GO! All units deployed! LFG! 🐸💎",
        "🐸 MISSION {id} LAUNCHED! Full send, no brakes! wagmi! 🚀",
        "💥 DEPLOY DEPLOY DEPLOY! Mission {id} is live! LFG fren! 🐸🔥",
    ],
    "run_status": [
        "📡 SITREP! Mission {id}: status={status}. hodl, fren! 🐸",
        "🐸 Mission {id} update: {status}. Stay diamond, ser! 📡💎",
        "🎯 INTEL REPORT! Mission {id} → {status}. hodl the line! 🐸",
    ],
    "run_notfound": [
        "❓ MISSION {id} NOT FOUND! Check your intel, ser! 🐸",
        "🐸 Mission {id}? That op doesn't exist, fren! ngmi! ❓",
        "💀 Mission {id} is a ghost. Wrong coordinates, ser! 🐸",
    ],
    "github_found": [
        "🐸 METAL SLUG! {n} repos spotted in the wild! based code! 💎",
        "💎 {n} repos found! Open source alpha, fren! 🐸🚀",
        "🔫 HEAVY BARREL! {n} code repos acquired. based devs! 🐸",
    ],
    "github_empty": [
        "👻 STEALTH MODE! No repos found. The code is hidden, ser! 🐸",
        "🐸 Zero repos, fren. The devs are in stealth mode! 👻",
        "💀 NO CODE! Devs are still building, ser. wen open source? 🐸",
    ],
    "codegen_found": [
        "💥 SUPER GRENADE! {n} code artifacts generated! wagmi! 🐸🚀",
        "🐸 {n} code drops! Fresh artifacts from the forge! LFG! 💥",
        "🔥 CODE BARRAGE! {n} artifacts ready to deploy, ser! 🐸💎",
    ],
    "codegen_empty": [
        "🐸 NO AMMO! Run the pipeline first, degen! wen codegen?",
        "💀 Zero code artifacts, fren. Pipeline hasn't cooked yet! 🐸",
        "📭 EMPTY CLIP! No codegen output. Run the pipeline, ser! 🐸",
    ],
    "error": [
        "💀 GAME OVER! {msg} ngmi! 🐸",
        "🐸 REKT! {msg} We'll get 'em next time, ser! 💀",
        "😤 CRITICAL HIT! {msg} ngmi fren! 🐸",
    ],
    "notation_added": [
        "🐸 NOTATION LOCKED! \\{name} is now custom ammo, ser! 💎",
        "💥 MACRO LOADED! \\{name} added to arsenal. Math goes brrr! 🐸",
    ],
    "notation_deleted": [
        "🐸 NOTATION PURGED! \\{name} is history, fren! 💀",
        "💥 MACRO REMOVED! \\{name} unloaded from arsenal! 🐸",
    ],
    "notation_list": [
        "🐸 AMMO INVENTORY! {n} custom notations loaded, ser! 💎",
        "💎 {n} macros in the arsenal! Custom math power! 🐸🔥",
    ],
    "notation_empty": [
        "📭 NO CUSTOM NOTATIONS! Add some with add_notation, fren! 🐸",
        "🐸 EMPTY ARSENAL! No macros loaded. Time to define some, ser! 📭",
    ],
}

PLAIN_MESSAGES: dict[str, str] = {
    "search_found": "{n} results found.",
    "search_empty": "No matches found.",
    "search_context": "{n} context chunks retrieved.",
    "list_papers": "{n} papers found.",
    "get_paper": "Paper #{id} retrieved.",
    "get_paper_notfound": "Paper #{id} not found.",
    "formulas_found": "{n} formulas found.",
    "formulas_empty": "No formulas found.",
    "run_start": "Pipeline run {id} started.",
    "run_status": "Run {id}: status={status}.",
    "run_notfound": "Run {id} not found.",
    "github_found": "{n} repos found.",
    "github_empty": "No repos found.",
    "codegen_found": "{n} code artifacts found.",
    "codegen_empty": "No generated code found.",
    "error": "Error: {msg}",
    "notation_added": "Notation \\{name} saved.",
    "notation_deleted": "Notation \\{name} removed.",
    "notation_list": "{n} custom notations.",
    "notation_empty": "No custom notations defined.",
}


def _flavor(key: str, **kwargs) -> str:
    """Return a flavored message string (random variant for arcade)."""
    if MCP_FLAVOR == "arcade":
        variants = ARCADE_MESSAGES.get(key)
        if variants:
            return random.choice(variants).format(**kwargs)
        return key
    template = PLAIN_MESSAGES.get(key, key)
    return template.format(**kwargs)


# -- HTTP helpers --


def _call_orchestrator(
    method: str,
    path: str,
    data: dict | None = None,
    timeout: int = 30,
) -> dict | list:
    """Make an HTTP request to the orchestrator service."""
    url = f"{ORCHESTRATOR_URL}{path}"
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"} if body else {},
        method=method,
    )
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
        return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        error_body = e.read().decode() if e.fp else str(e)
        try:
            return json.loads(error_body)
        except (json.JSONDecodeError, ValueError):
            raise RuntimeError(f"Orchestrator {method} {path}: {e.code} {error_body}")
    except urllib.error.URLError as e:
        raise RuntimeError(
            f"Cannot reach orchestrator at {ORCHESTRATOR_URL}: {e.reason}"
        )


# -- MCP Server --

MCP_PORT = int(os.environ.get("RP_MCP_PORT", "8776"))

mcp = FastMCP(
    "PePeRS",
    instructions=(
        "PePeRS (Paper Extraction, Processing, Evaluation, Retrieval & Synthesis) "
        "is an academic paper processing pipeline. Use these tools to search papers, "
        "extract formulas, validate math, generate code, and discover GitHub implementations."
    ),
    host="0.0.0.0",
    port=MCP_PORT,
)


@mcp.tool()
def search_papers(
    query: str,
    mode: str = "hybrid",
    context_only: bool = False,
) -> str:
    """Search academic papers using RAG-powered semantic search.

    Args:
        query: Natural language search query (e.g. "Kelly criterion stochastic volatility")
        mode: Search mode - hybrid, local, global, mix, naive, bypass
        context_only: If true, returns raw context chunks without LLM synthesis (faster, <2s)
    """
    try:
        result = _call_orchestrator("POST", "/search", {
            "query": query,
            "mode": mode,
            "context_only": context_only,
        })
    except RuntimeError as e:
        return _flavor("error", msg=str(e))

    if not isinstance(result, dict):
        return _flavor("error", msg="Invalid orchestrator response type")

    if context_only:
        context = result.get("context", "")
        chunks = context.split("\n\n") if context else []
        header = _flavor("search_context", n=len(chunks))
        return f"{header}\n\n{context}" if context else _flavor("search_empty")

    answer = result.get("answer", "")
    if answer:
        header = _flavor("search_found", n=1)
        return f"{header}\n\n{answer}"
    return _flavor("search_empty")


@mcp.tool()
def list_papers(stage: str = "", limit: int = 50) -> str:
    """List papers in the pipeline database.

    Args:
        stage: Filter by pipeline stage (discovered, analyzed, extracted, validated, codegen). Empty for all.
        limit: Maximum number of papers to return (1-200)
    """
    try:
        params = f"?limit={min(limit, 200)}"
        if stage:
            params += f"&stage={stage}"
        result = _call_orchestrator("GET", f"/papers{params}")
    except RuntimeError as e:
        return _flavor("error", msg=str(e))

    if not isinstance(result, list):
        return _flavor("error", msg="Unexpected response format")

    if not result:
        return _flavor("search_empty")

    header = _flavor("list_papers", n=len(result))
    lines = [header, ""]
    for p in result:
        lines.append(
            f"- **#{p['id']}** [{p.get('stage', '?')}] {p.get('title', 'Untitled')}"
        )
    return "\n".join(lines)


@mcp.tool()
def get_paper(paper_id: int) -> str:
    """Get detailed information about a specific paper including its formulas.

    Args:
        paper_id: The paper ID from the pipeline database
    """
    try:
        result = _call_orchestrator("GET", f"/papers?id={paper_id}")
    except RuntimeError as e:
        return _flavor("error", msg=str(e))

    if not isinstance(result, dict) or "error" in result:
        return _flavor("get_paper_notfound", id=paper_id)

    header = _flavor("get_paper", id=paper_id)
    title = result.get("title", "Untitled")
    stage = result.get("stage", "?")
    abstract = result.get("abstract", "")[:300]
    arxiv_id = result.get("arxiv_id", "")
    formulas = result.get("formulas", [])

    lines = [
        header,
        "",
        f"**Title**: {title}",
        f"**arXiv**: {arxiv_id}",
        f"**Stage**: {stage}",
        f"**Formulas**: {len(formulas)}",
    ]
    if abstract:
        lines.extend(["", f"**Abstract**: {abstract}..."])

    if formulas:
        lines.extend(["", "**Top formulas**:"])
        for f in formulas[:10]:
            latex = f.get("latex", "?")[:80]
            fstage = f.get("stage", "?")
            lines.append(f"  - `{latex}` [{fstage}]")
        if len(formulas) > 10:
            lines.append(f"  ... and {len(formulas) - 10} more")

    return "\n".join(lines)


@mcp.tool()
def get_formulas(paper_id: int, stage: str = "", limit: int = 50) -> str:
    """Get formulas for a specific paper.

    Args:
        paper_id: The paper ID
        stage: Filter by formula stage (extracted, validated, codegen). Empty for all.
        limit: Maximum number of formulas (1-200)
    """
    try:
        params = f"?paper_id={paper_id}&limit={min(limit, 200)}"
        if stage:
            params += f"&stage={stage}"
        result = _call_orchestrator("GET", f"/formulas{params}")
    except RuntimeError as e:
        return _flavor("error", msg=str(e))

    if not isinstance(result, list):
        return _flavor("error", msg="Unexpected response format")

    if not result:
        return _flavor("formulas_empty")

    header = _flavor("formulas_found", n=len(result))
    lines = [header, ""]
    for f in result:
        fid = f.get("id", "?")
        latex = f.get("latex", "?")[:100]
        fstage = f.get("stage", "?")
        desc = f.get("description", "")
        line = f"- **#{fid}** [{fstage}] `{latex}`"
        if desc:
            line += f" — {desc[:60]}"
        lines.append(line)
    return "\n".join(lines)


@mcp.tool()
def run_pipeline(
    query: str = "",
    paper_id: int = 0,
    stages: int = 5,
    max_papers: int = 10,
    max_formulas: int = 50,
) -> str:
    """Trigger an async pipeline run (discovery -> analysis -> extraction -> validation -> codegen).

    Args:
        query: arXiv search query. Empty to process existing papers.
        paper_id: Process a specific paper by ID (0 to skip).
        stages: Number of pipeline stages to run (1-5).
        max_papers: Maximum papers to process per run.
        max_formulas: Maximum formulas to process per run.
    """
    payload: dict = {"stages": stages, "max_papers": max_papers, "max_formulas": max_formulas}
    if query:
        payload["query"] = query
    if paper_id > 0:
        payload["paper_id"] = paper_id

    try:
        result = _call_orchestrator("POST", "/run", payload, timeout=10)
    except RuntimeError as e:
        return _flavor("error", msg=str(e))

    if not isinstance(result, dict):
        return _flavor("error", msg="Invalid orchestrator response type")

    run_id = result.get("run_id", "unknown")
    return _flavor("run_start", id=run_id)


@mcp.tool()
def get_run_status(run_id: str) -> str:
    """Check the status of a pipeline run.

    Args:
        run_id: The run ID returned by run_pipeline
    """
    try:
        result = _call_orchestrator("GET", f"/runs?id={run_id}")
    except RuntimeError as e:
        return _flavor("error", msg=str(e))

    if not isinstance(result, dict) or "error" in result:
        return _flavor("run_notfound", id=run_id)

    status = result.get("status", "unknown")
    header = _flavor("run_status", id=run_id, status=status)

    lines = [header]
    if result.get("stages_completed") is not None:
        lines.append(
            f"Stages: {result['stages_completed']}/{result.get('stages_requested', '?')}"
        )
    if result.get("papers_processed") is not None:
        lines.append(f"Papers processed: {result['papers_processed']}")
    if result.get("error"):
        lines.append(f"Error: {result['error']}")

    return "\n".join(lines)


@mcp.tool()
def search_github(
    paper_id: int,
    max_repos: int = 3,
    min_stars: int = 5,
) -> str:
    """Search GitHub for code implementations of a paper.

    Args:
        paper_id: The paper ID to search implementations for
        max_repos: Maximum repos to return (1-10)
        min_stars: Minimum GitHub stars filter
    """
    try:
        result = _call_orchestrator("POST", "/search-github", {
            "paper_id": paper_id,
            "max_repos": max_repos,
            "min_stars": min_stars,
        }, timeout=60)
    except RuntimeError as e:
        return _flavor("error", msg=str(e))

    if not isinstance(result, dict):
        return _flavor("error", msg="Unexpected response format")

    repos = result.get("repos", [])
    if not repos:
        return _flavor("github_empty")

    header = _flavor("github_found", n=len(repos))
    lines = [header, ""]
    for repo in repos:
        r = repo if isinstance(repo, dict) else {}
        name = r.get("full_name", r.get("repo", {}).get("full_name", "?"))
        stars = r.get("stars", r.get("repo", {}).get("stars", 0))
        url = r.get("url", r.get("repo", {}).get("url", ""))
        analysis = r.get("analysis", {})
        rec = analysis.get("recommendation", "") if analysis else ""
        lines.append(f"- **{name}** ({stars} stars) {url}")
        if rec:
            lines.append(f"  Recommendation: {rec}")
    return "\n".join(lines)


@mcp.tool()
def get_generated_code(
    paper_id: int,
    language: str = "",
    limit: int = 50,
) -> str:
    """Get generated code for a paper's formulas.

    Args:
        paper_id: The paper ID
        language: Filter by programming language (python, matlab, etc). Empty for all.
        limit: Maximum code entries (1-200)
    """
    try:
        params = f"?paper_id={paper_id}&limit={min(limit, 200)}"
        if language:
            params += f"&language={language}"
        result = _call_orchestrator("GET", f"/generated-code{params}")
    except RuntimeError as e:
        return _flavor("error", msg=str(e))

    if not isinstance(result, list):
        return _flavor("error", msg="Unexpected response format")

    if not result:
        return _flavor("codegen_empty")

    header = _flavor("codegen_found", n=len(result))
    lines = [header, ""]
    for entry in result:
        fid = entry.get("formula_id", "?")
        lang = entry.get("language", "?")
        latex = entry.get("latex", "")[:60]
        code = entry.get("code", "")
        lines.append(f"### Formula #{fid} ({lang})")
        if latex:
            lines.append(f"LaTeX: `{latex}`")
        if code:
            lines.append(f"```{lang}\n{code}\n```")
        lines.append("")
    return "\n".join(lines)


@mcp.tool()
def add_notation(
    name: str,
    body: str,
    nargs: int = 0,
    description: str = "",
) -> str:
    """Add or update a custom LaTeX notation for macro expansion.

    Custom notations are expanded in extracted formulas before CAS validation.
    Uses upsert: if the notation exists, it updates it.

    Args:
        name: Macro name without backslash (e.g. "Expect", "KL", "Var")
        body: LaTeX replacement with #1, #2 placeholders (e.g. "\\mathbb{E}\\left[#1\\right]")
        nargs: Number of arguments (0-9)
        description: Optional description of what this notation means
    """
    try:
        result = _call_orchestrator("POST", "/notations", {
            "name": name,
            "body": body,
            "nargs": nargs,
            "description": description,
        })
    except RuntimeError as e:
        return _flavor("error", msg=str(e))

    if isinstance(result, dict) and result.get("success"):
        return _flavor("notation_added", name=name)
    msg = result.get("error", "Unknown error") if isinstance(result, dict) else "Bad response"
    return _flavor("error", msg=msg)


@mcp.tool()
def list_notations() -> str:
    """List all custom LaTeX notations defined for macro expansion."""
    try:
        result = _call_orchestrator("GET", "/notations")
    except RuntimeError as e:
        return _flavor("error", msg=str(e))

    if not isinstance(result, list) or not result:
        return _flavor("notation_empty")

    header = _flavor("notation_list", n=len(result))
    lines = [header, ""]
    for n in result:
        nargs = n.get("nargs", 0)
        args_str = "".join(f"{{#{i + 1}}}" for i in range(nargs)) if nargs else ""
        lines.append(f"- **\\{n['name']}**{args_str} → `{n['body']}`")
        if n.get("description"):
            lines.append(f"  _{n['description']}_")
    return "\n".join(lines)


@mcp.tool()
def remove_notation(name: str) -> str:
    """Remove a custom LaTeX notation.

    Args:
        name: Macro name without backslash (e.g. "Expect")
    """
    try:
        result = _call_orchestrator("POST", "/notations/delete", {"name": name})
    except RuntimeError as e:
        return _flavor("error", msg=str(e))

    if isinstance(result, dict) and result.get("success"):
        return _flavor("notation_deleted", name=name)
    msg = result.get("error", "Unknown error") if isinstance(result, dict) else "Bad response"
    return _flavor("error", msg=msg)
