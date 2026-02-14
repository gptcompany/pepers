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

    Supports 2+ engines with graceful degradation (fallback). If an engine
    fails but >=2 others succeed and agree, their consensus is used.

    Decision logic:
      0 succeed           → UNPARSEABLE
      1 succeeds          → PARTIAL  (insufficient for consensus)
      >=2 succeed, agree  → VALID or INVALID
      >=2 succeed, split  → INVALID  (disagreement)
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

    if len(successful) == 1:
        ok_engine = successful[0]
        return ConsensusResult(
            outcome=ConsensusOutcome.PARTIAL,
            detail=f"Only {ok_engine.engine} succeeded, {len(failed)} engine(s) errored",
            engine_count=len(engine_results),
            agree_count=1,
        )

    # >=2 engines succeeded — check agreement (fallback: ignore failed engines)
    valid_results = [r for r in successful if r.is_valid]
    invalid_results = [r for r in successful if not r.is_valid]

    failed_note = ""
    if failed:
        failed_names = ", ".join(r.engine for r in failed)
        failed_note = f" ({failed_names} errored, fallback used)"

    if len(valid_results) == len(successful):
        return ConsensusResult(
            outcome=ConsensusOutcome.VALID,
            detail=f"All {len(successful)} engines agree: valid{failed_note}",
            engine_count=len(engine_results),
            agree_count=len(successful),
        )

    if len(invalid_results) == len(successful):
        return ConsensusResult(
            outcome=ConsensusOutcome.INVALID,
            detail=f"All {len(successful)} engines agree: invalid{failed_note}",
            engine_count=len(engine_results),
            agree_count=len(successful),
        )

    # Disagreement
    return ConsensusResult(
        outcome=ConsensusOutcome.INVALID,
        detail=f"Engines disagree: {len(valid_results)} valid, {len(invalid_results)} invalid{failed_note}",
        engine_count=len(engine_results),
        agree_count=max(len(valid_results), len(invalid_results)),
    )
