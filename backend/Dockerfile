# syntax=docker/dockerfile:1

FROM python:3.11-slim AS base
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH="/app/.venv/bin:$PATH"
COPY --from=ghcr.io/astral-sh/uv:0.12.7 /uv /uvx /bin/
WORKDIR /app

# 1. Install dependencies against the lockfile (cached unless the lock changes).
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

# 2. Install the application itself.
COPY README.md alembic.ini ./
COPY alembic ./alembic
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

EXPOSE 8000
CMD ["uvicorn", "quantscope.main:app", "--host", "0.0.0.0", "--port", "8000"]
