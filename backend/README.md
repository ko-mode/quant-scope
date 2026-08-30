# QuantScope backend

FastAPI + SQLAlchemy + Alembic. Pure quantitative analytics live in
`src/quantscope/quant/` and must not import web, database, or configuration
modules (enforced by `import-linter`).

See the repository root `README.md` for setup and the `docs/` directory for
architecture and decision records.

## Common commands (run from `backend/`)

```bash
uv sync                       # install runtime + dev dependencies
uv run uvicorn quantscope.main:app --reload   # run the API
uv run pytest                 # tests
uv run ruff check . && uv run ruff format --check .
uv run mypy                   # type check
uv run lint-imports           # verify the quant dependency boundary
uv run alembic history        # migration history (none until Phase 1)
```
