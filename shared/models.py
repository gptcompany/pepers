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

from datetime import datetime
from enum import Enum

from pydantic import BaseModel


class PipelineStage(str, Enum):
    """Pipeline processing stages."""

    DISCOVERED = "discovered"
    ANALYZED = "analyzed"
    EXTRACTED = "extracted"
    VALIDATED = "validated"
    CODEGEN = "codegen"
    COMPLETE = "complete"
    FAILED = "failed"


class Paper(BaseModel):
    """Academic paper metadata.

    Populated by Discovery service (arXiv API + Semantic Scholar/CrossRef).
    """

    ...


class Formula(BaseModel):
    """Extracted LaTeX formula from a paper.

    Populated by Extractor service (RAGAnything + regex).
    """

    ...


class Validation(BaseModel):
    """CAS validation result.

    Populated by Validator service (SymPy + Wolfram + Maxima consensus).
    """

    ...


class GeneratedCode(BaseModel):
    """Generated code from a validated formula.

    Populated by Codegen service (LLM + SymPy + Rust AST).
    """

    ...


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

    ...


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
