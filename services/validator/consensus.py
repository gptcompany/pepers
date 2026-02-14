"""Consensus logic for multi-CAS validation results.

Applies all-or-nothing consensus: all engines must agree for VALID.
Any disagreement or error results in INVALID, PARTIAL, or UNPARSEABLE.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ConsensusOutcome(str, Enum):
    VALID = "valid"
    INVALID = "invalid"
    PARTIAL = "partial"
    UNPARSEABLE = "unparseable"


@dataclass
class ConsensusResult:
    outcome: ConsensusOutcome
    detail: str
    engine_count: int
    agree_count: int


def apply_consensus(engine_results: list) -> ConsensusResult:
    """Apply consensus logic to per-engine validation results.

    Decision matrix (2 engines: SymPy + Maxima):

    | SymPy      | Maxima     | Outcome      |
    |------------|------------|--------------|
    | valid      | valid      | VALID        |
    | valid      | invalid    | INVALID      |
    | invalid    | valid      | INVALID      |
    | invalid    | invalid    | INVALID      |
    | valid      | error      | PARTIAL      |
    | error      | valid      | PARTIAL      |
    | invalid    | error      | PARTIAL      |
    | error      | invalid    | PARTIAL      |
    | error      | error      | UNPARSEABLE  |
    """
    successful = [r for r in engine_results if r.success]
    failed = [r for r in engine_results if not r.success]

    if len(successful) == 0:
        return ConsensusResult(
            outcome=ConsensusOutcome.UNPARSEABLE,
            detail=f"All {len(engine_results)} engines failed to parse",
            engine_count=len(engine_results),
            agree_count=0,
        )

    if len(failed) > 0 and len(successful) > 0:
        ok_engine = successful[0]
        return ConsensusResult(
            outcome=ConsensusOutcome.PARTIAL,
            detail=f"Only {ok_engine.engine} succeeded, {len(failed)} engine(s) errored",
            engine_count=len(engine_results),
            agree_count=1,
        )

    # All engines succeeded — check agreement
    valid_results = [r for r in successful if r.is_valid]
    invalid_results = [r for r in successful if not r.is_valid]

    if len(valid_results) == len(successful):
        return ConsensusResult(
            outcome=ConsensusOutcome.VALID,
            detail=f"All {len(successful)} engines agree: valid",
            engine_count=len(engine_results),
            agree_count=len(successful),
        )

    if len(invalid_results) == len(successful):
        return ConsensusResult(
            outcome=ConsensusOutcome.INVALID,
            detail=f"All {len(successful)} engines agree: invalid",
            engine_count=len(engine_results),
            agree_count=len(successful),
        )

    # Disagreement
    return ConsensusResult(
        outcome=ConsensusOutcome.INVALID,
        detail=f"Engines disagree: {len(valid_results)} valid, {len(invalid_results)} invalid",
        engine_count=len(engine_results),
        agree_count=max(len(valid_results), len(invalid_results)),
    )
