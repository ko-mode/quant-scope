"""Guard test for the pure-analytics boundary.

`import-linter` is the authoritative check (run in CI and pre-commit). This test
is a fast, dependency-free smoke check so a boundary violation also fails the
normal `pytest` run.
"""

from __future__ import annotations

import importlib
import pkgutil

# Mirror of the import-linter forbidden contract in pyproject.toml (ADR 0002).
# quantscope.quant may import only the stdlib + numpy/pandas/scipy/statsmodels/pandera.
FORBIDDEN_PREFIXES = (
    "fastapi",
    "starlette",
    "uvicorn",
    "sqlalchemy",
    "alembic",
    "psycopg",
    "httpx",
    "requests",
    "pydantic",
    "pydantic_settings",
    "yfinance",
    "pandas_datareader",
    "quantscope.api",
    "quantscope.services",
    "quantscope.data",
    "quantscope.db",
    "quantscope.config",
    "quantscope.main",
    "quantscope.jobs",
)


def _walk_quant_modules() -> list[str]:
    import quantscope.quant as pkg

    names = [pkg.__name__]
    for info in pkgutil.walk_packages(pkg.__path__, prefix=f"{pkg.__name__}."):
        names.append(info.name)
    return names


def test_quant_package_has_no_forbidden_imports() -> None:
    for module_name in _walk_quant_modules():
        module = importlib.import_module(module_name)
        for attr in vars(module).values():
            mod = getattr(attr, "__module__", "")
            assert not mod.startswith(
                FORBIDDEN_PREFIXES
            ), f"{module_name} exposes symbol from forbidden module {mod!r}"
