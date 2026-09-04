"""Shared result and error types for the analytics engine.

Three failure shapes are distinguished so a caller can tell "you gave me bad
data" from "the number is legitimately unavailable":

* :class:`QuantInputError` - the input violates a structural precondition (wrong
  index type, unsorted or duplicated dates, non-finite values, non-positive
  prices). **Raised**, because it means an upstream bug.
* :class:`InsufficientObservations` - the input is well-formed but shorter than
  the metric's minimum-observation gate (ADR 0017). **Returned**; the field
  names match the ADR wire contract verbatim.
* :class:`UndefinedResult` - there is enough data, but the statistic is
  mathematically undefined for it (a zero-variance denominator). **Returned**.
"""

from __future__ import annotations

from dataclasses import dataclass


class QuantInputError(ValueError):
    """A price or return series violates a structural precondition."""


@dataclass(frozen=True, slots=True)
class InsufficientObservations:
    """Metric suppressed: fewer usable observations than the gate (ADR 0017)."""

    metric: str
    required: int
    observations_used: int
    status: str = "insufficient_observations"


@dataclass(frozen=True, slots=True)
class UndefinedResult:
    """Metric undefined for this input despite sufficient observations."""

    metric: str
    reason: str
    observations_used: int
    status: str = "undefined"


__all__ = ["InsufficientObservations", "QuantInputError", "UndefinedResult"]
