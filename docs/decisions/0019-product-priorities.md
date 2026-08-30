# 19. Product priorities (CV project)

- **Status:** Accepted
- **Date:** 2026-08-30

## Context

Scope and effort trade-offs recur constantly. Without an agreed ranking they get
decided ad hoc and inconsistently. The primary audience for this repository is a
**technical hiring manager evaluating a CV project**, not end investors.

## Decision

When two goals conflict, the earlier one wins:

1. **Quantitative correctness** - right numbers, right conventions, tested.
2. **Architectural clarity and ADR quality** - clean boundaries, readable
   structure, decisions written down and justified.
3. **Polished research dashboard** - the visible artefact; it should look and
   feel considered.
4. **Reproducible local setup** - one clone + documented steps to a running
   stack.
5. **Comparison and Fama-French 3-factor methodology** - the headline
   analytical features done properly.
6. **Feature breadth** - more endpoints/metrics only after 1-5 hold.

## Consequences

- Time goes to correctness tests and ADRs before extra features.
- A smaller set of well-executed, well-explained features is preferred over a
  broad shallow one.
- "We could also add X" is deferred by default unless it serves a higher
  priority.

## Alternatives considered

- **Breadth-first (many features, lighter rigour)** - rejected: the opposite of
  what the audience is assessing.
- **Dashboard-first** - rejected: a polished UI over shaky numbers is a net
  negative for this audience.
