"""Pure quantitative analytics.

Every function in this package must be:

* **Deterministic** - same inputs produce the same outputs, always.
* **I/O-free** - no network, no filesystem, no database, no clock.
* **Framework-free** - no FastAPI, SQLAlchemy, Alembic, or pydantic imports.
  Inputs and outputs are numpy/pandas objects (validated at the boundary with
  pandera from Phase 2) or plain dataclasses.

The boundary is enforced by the ``import-linter`` contract in ``pyproject.toml``
and checked in CI. Callers in the service layer are responsible for loading
data, converting to/from wire schemas, and attaching the ``assumptions``
metadata block to responses.

No analytics are implemented yet; the first functions (returns, volatility,
Sharpe, beta, drawdown, historical VaR / Expected Shortfall) arrive in Phase 2.
"""
