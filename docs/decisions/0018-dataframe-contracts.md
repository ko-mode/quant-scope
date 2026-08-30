# 18. DataFrame contracts at the quant boundary

- **Status:** Accepted
- **Date:** 2026-08-30

## Context

The quant engine works on time series. It needs typed, validated inputs and
outputs at its public boundary without inventing a parallel type system that
fights pandas ergonomics.

## Decision

- Public `quantscope.quant` functions take and return `pandas.Series` /
  `pandas.DataFrame`, plus plain `@dataclass` objects for scalar result bundles
  (e.g. a drawdown summary).
- Canonical frame shapes - price panel, return panel, factor panel - are defined
  as **Pandera** schemas in `quantscope.quant.frames`, capturing column names,
  dtypes, index type (a sorted unique `DatetimeIndex` on XNYS sessions), and
  invariants (e.g. no duplicate dates, prices > 0).
- Schemas are validated **at the public boundary** of the engine
  (`schema.validate(df)` on entry), not repeatedly deep in the call stack.
- **No custom DataFrame wrapper classes** (`PriceFrame`, `ReturnFrame`, ...)
  created solely to satisfy static typing.

## Consequences

- Familiar pandas API everywhere; easy interop with numpy/scipy/statsmodels.
- Malformed inputs fail fast with a clear Pandera error naming the offending
  column/row.
- Static typing sees `DataFrame`, not the column set - accepted; Pandera covers
  structure and invariants at runtime, and golden-value tests cover behaviour.

## Alternatives considered

- **Custom wrapper/newtype classes** - rejected: ceremony, constant
  wrap/unwrap, poor library interop.
- **`pandas-stubs` + `TypedDict` row models** - insufficient for row-wise and
  index invariants.
- **No validation, just conventions** - rejected: correctness is priority 1.
