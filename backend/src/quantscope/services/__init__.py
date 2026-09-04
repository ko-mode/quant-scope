"""Application services: use-case orchestration between the API and the engine.

A service loads persisted data through :mod:`quantscope.db.repositories`, calls
the pure :mod:`quantscope.quant` engine, assembles the ADR 0005 ``assumptions``
block, and maps engine result dataclasses to API schemas. It holds no SQL and
raises no HTTP status codes - the router owns those.
"""
