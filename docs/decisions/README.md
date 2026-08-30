# Architecture Decision Records

Short records of the decisions that shape QuantScope. Each ADR states the
context, the decision, its consequences, and the alternatives considered.

Format: lightweight [MADR](https://adr.github.io/madr/). One decision per file.
Superseding a decision means adding a new ADR and marking the old one
`Superseded by NNNN`, not editing history.

| #    | Decision                                             | Status   |
|------|-----------------------------------------------------|----------|
| 0001 | Modular monolith, not microservices                 | Accepted |
| 0002 | Pure `quant` package with a CI-enforced import boundary | Accepted |
| 0003 | Provider abstraction + ingestion separate from analytics | Accepted |
| 0004 | PostgreSQL with provenance fields; defer point-in-time tables | Accepted |
| 0005 | `assumptions` metadata block in every analytics response | Accepted |
| 0006 | US equities and a single exchange calendar (XNYS) for V1 | Accepted |
| 0007 | No auth, Redis, queue or workers in V1              | Accepted |
| 0008 | Stooq as the initial price provider                 | Accepted |
| 0009 | Daily Fama-French factors for V1; schema supports monthly | Accepted |
| 0010 | TanStack Query as the frontend data layer           | Accepted |
| 0011 | `security_id` is the universal foreign key          | Accepted |
| 0012 | Total return via vendor adjusted close              | Accepted |
| 0013 | Risk-free rate from the Ken French `RF` series      | Accepted |
| 0014 | Python tooling: uv, Ruff, mypy, pytest, import-linter | Accepted |
| 0015 | No redistributed vendor data in the repository      | Accepted |
| 0016 | Canonical-metric mapping for fundamentals           | Accepted |
| 0017 | Quantitative conventions and observation thresholds (V1) | Accepted |
| 0018 | DataFrame contracts at the quant boundary           | Accepted |
| 0019 | Product priorities (CV project)                     | Accepted |
| 0020 | Thin cross-platform task runner (`justfile`)        | Accepted |
