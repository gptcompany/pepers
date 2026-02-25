"""Pydantic models for the research pipeline.

Shared data models used by all services. Provides validation,
serialization, and type safety across the pipeline.

All models use Pydantic v2 with strict validation.
Serialization to/from JSON and SQLite-compatible dicts.

Models:
- Paper: Academic paper metadata from arXiv + enrichment
- Formula: Extracted LaTeX formula from a paper
- Validation: CAS validation result for a formula
- GeneratedCode: Generated Python/Rust code from a formula
- ServiceStatus: Standard /health and /status response
- ProcessRequest: Base request for /process endpoint
- ProcessResponse: Base response for /process endpoint
- ErrorResponse: Standard error response format
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator, model_validator


class PipelineStage(str, Enum):
    """Pipeline processing stages."""

    DISCOVERED = "discovered"
    ANALYZED = "analyzed"
    REJECTED = "rejected"
    EXTRACTED = "extracted"
    VALIDATED = "validated"
    CODEGEN = "codegen"
    COMPLETE = "complete"
    FAILED = "failed"


def _parse_json_list(v: Any) -> list:
    """Parse a JSON string to list, or return as-is if already a list."""
    if v is None:
        return []
    if isinstance(v, str):
        return json.loads(v)
    return list(v)


def _parse_json_dict(v: Any) -> dict | None:
    """Parse a JSON string to dict, or return as-is if already a dict."""
    if v is None:
        return None
    if isinstance(v, str):
        return json.loads(v)
    return dict(v)


class Paper(BaseModel):
    """Academic paper metadata.

    Populated by Discovery service (arXiv/OpenAlex + Semantic Scholar/CrossRef).
    """

    model_config = ConfigDict(from_attributes=True)

    id: int | None = None
    arxiv_id: str | None = None
    title: str
    abstract: str | None = None
    authors: list[str] = []
    categories: list[str] = []
    doi: str | None = None
    pdf_url: str | None = None
    published_date: datetime | None = None
    # Semantic Scholar enrichment
    semantic_scholar_id: str | None = None
    citation_count: int = 0
    reference_count: int = 0
    influential_citation_count: int = 0
    venue: str | None = None
    fields_of_study: list[str] = []
    tldr: str | None = None
    open_access: bool = False
    # CrossRef enrichment
    crossref_data: dict | None = None
    # Multi-source tracking
    source: str = "arxiv"
    openalex_id: str | None = None
    # Pipeline state
    stage: PipelineStage = PipelineStage.DISCOVERED
    score: float | None = None
    error: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @field_validator("authors", "categories", "fields_of_study", mode="before")
    @classmethod
    def parse_json_list(cls, v: object) -> list:
        return _parse_json_list(v)

    @field_validator("crossref_data", mode="before")
    @classmethod
    def parse_json_dict(cls, v: object) -> dict | None:
        return _parse_json_dict(v)


class Formula(BaseModel):
    """Extracted LaTeX formula from a paper.

    Populated by Extractor service (RAGAnything + regex).
    """

    model_config = ConfigDict(from_attributes=True)

    id: int | None = None
    paper_id: int
    latex: str
    latex_hash: str = ""
    description: str | None = None
    formula_type: str | None = None
    context: str | None = None
    stage: PipelineStage = PipelineStage.EXTRACTED
    error: str | None = None
    created_at: datetime | None = None

    @model_validator(mode="before")
    @classmethod
    def compute_latex_hash(cls, values: dict) -> dict:
        if isinstance(values, dict):
            if not values.get("latex_hash") and values.get("latex"):
                values["latex_hash"] = hashlib.sha256(
                    values["latex"].encode()
                ).hexdigest()
        return values


class Validation(BaseModel):
    """CAS validation result.

    Populated by Validator service (multi-engine consensus via CAS microservice).
    """

    model_config = ConfigDict(from_attributes=True)

    id: int | None = None
    formula_id: int
    engine: str
    is_valid: bool | None = None
    result: str | None = None
    error: str | None = None
    time_ms: int | None = None
    created_at: datetime | None = None


class FormulaExplanation(BaseModel):
    """LLM-generated explanation of a validated formula.

    Populated by Codegen service. Stored as JSON in formulas.description.
    Validation-only model (no DB table).
    """

    explanation: str
    variables: list[dict[str, str]] = []
    assumptions: list[str] = []
    domain: str = ""


class GeneratedCode(BaseModel):
    """Generated code from a validated formula.

    Populated by Codegen service (LLM + SymPy + Rust AST).
    """

    model_config = ConfigDict(from_attributes=True)

    id: int | None = None
    formula_id: int
    language: str
    code: str
    metadata: dict | None = None
    stage: PipelineStage = PipelineStage.CODEGEN
    error: str | None = None
    created_at: datetime | None = None

    @field_validator("metadata", mode="before")
    @classmethod
    def parse_metadata(cls, v: object) -> dict | None:
        return _parse_json_dict(v)


class LLMCodegenResult(BaseModel):
    """LLM-generated Python code from LaTeX (Layer 5 fallback).

    Used when SymPy parse_latex fails and we fall back to LLM codegen.
    Only Python output — C99/Rust remain errors for safety.
    """

    python_code: str
    variables: list[str] = []
    description: str = ""


class ServiceStatus(BaseModel):
    """Standard response for /health and /status endpoints.

    All services must return this format.
    """

    status: str = "ok"
    service: str
    version: str
    uptime_seconds: float = 0.0
    last_processed: datetime | None = None


class ProcessRequest(BaseModel):
    """Base request for /process endpoint.

    Each service extends this with service-specific fields.
    """

    paper_id: int | None = None
    formula_id: int | None = None
    force: bool = False


class ProcessResponse(BaseModel):
    """Base response for /process endpoint.

    Each service extends this with service-specific fields.
    """

    success: bool
    service: str
    time_ms: int = 0
    error: str | None = None


class ErrorResponse(BaseModel):
    """Standard error response format.

    Returned for all 4xx/5xx responses. AI agents parse this format.
    """

    error: str
    code: str
    details: dict | None = None


class GitHubRepo(BaseModel):
    """Discovered GitHub repository for a paper."""

    model_config = ConfigDict(from_attributes=True)

    id: int | None = None
    paper_id: int
    full_name: str
    url: str
    clone_url: str
    description: str | None = None
    stars: int = 0
    language: str | None = None
    updated_at: str | None = None
    topics: list[str] = []
    search_query: str | None = None
    created_at: datetime | None = None

    @field_validator("topics", mode="before")
    @classmethod
    def parse_topics(cls, v: object) -> list:
        return _parse_json_list(v)


class GitHubAnalysis(BaseModel):
    """Gemini analysis result for a GitHub repository."""

    model_config = ConfigDict(from_attributes=True)

    id: int | None = None
    repo_id: int
    relevance_score: int | None = None
    quality_score: int | None = None
    formula_matches: list[dict] = []
    summary: str | None = None
    recommendation: str | None = None
    key_files: list[str] = []
    dependencies: list[str] = []
    model_used: str | None = None
    analysis_time_ms: int | None = None
    error: str | None = None
    created_at: datetime | None = None

    @field_validator("formula_matches", "key_files", "dependencies", mode="before")
    @classmethod
    def parse_json_lists(cls, v: object) -> list:
        return _parse_json_list(v)


class SearchGitHubRequest(BaseModel):
    """Request body for POST /search-github."""

    paper_id: int
    max_repos: int = 3
    languages: list[str] = ["python", "rust", "cpp"]
    min_stars: int = 5
    query_override: str | None = None
    force: bool = False


class SearchGitHubResponse(BaseModel):
    """Response for POST /search-github."""

    paper_id: int
    repos_found: int
    repos_analyzed: int
    results: list[dict] = []
    errors: list[str] = []


class CustomNotation(BaseModel):
    """Custom LaTeX notation for macro expansion before CAS validation."""

    model_config = ConfigDict(from_attributes=True)

    id: int | None = None
    name: str
    body: str
    nargs: int = 0
    description: str = ""
    created_at: datetime | None = None
    updated_at: datetime | None = None
