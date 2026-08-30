"""QuantScope backend package.

Layering (outer depends inward, never the reverse):

    api  ->  services  ->  quant / data  ->  db

`quantscope.quant` is a pure analytics library: deterministic functions over
numpy/pandas with no I/O and no dependency on FastAPI, SQLAlchemy, or settings.
This is enforced in CI by `import-linter`.
"""

__version__ = "0.1.0"
