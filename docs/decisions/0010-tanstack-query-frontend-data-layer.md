# 10. TanStack Query as the frontend data layer

- **Status:** Accepted
- **Date:** 2026-08-30

## Context

The dashboard is read-heavy: many endpoints, overlapping requests (a ticker page
and a comparison view share series), and a need for caching, background refresh
and consistent loading/error states. Server state is not application state and
should not live in a general-purpose store.

## Decision

Use **TanStack Query** (`@tanstack/react-query`) as the single data layer for
server state. One `QueryClient` per browser session, provided by
`src/app/providers.tsx` (a client component). Query keys are structured by
resource and parameters. The typed fetch client (`src/lib/api/client.ts`, later
generated from OpenAPI) is the transport; components call hooks, never `fetch`.

No Redux/Zustand/Jotai for server data. Local UI state uses React state.

## Consequences

- Caching, de-duplication, retry and refetch are handled once, uniformly.
- Server components still render shell/layout; interactive data views are client
  components using the hooks.
- Contributors must follow the query-key convention for cache correctness.

## Alternatives considered

- **Plain `fetch` in `useEffect`** - rejected: reinvents caching, races and
  error handling per component.
- **RTK Query / SWR** - reasonable, not chosen: TanStack Query has the richest
  feature set for this use and no Redux buy-in.
