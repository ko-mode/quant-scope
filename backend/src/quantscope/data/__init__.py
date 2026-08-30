"""External data acquisition: source-specific providers, normalisation, and
ingestion orchestration.

The request path never imports this package; ingestion is driven by CLI jobs
(``quantscope.jobs``). Providers are the only place vendor/source quirks live
(ADR 0003).
"""
