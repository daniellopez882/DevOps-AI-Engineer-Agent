# ADR 0002 — Every event is signed or keyed, validated, and answered with an id

**Status:** accepted

## Context

Reproduced on the original: `POST /webhook` with no headers and
`{"trigger_type": "nonsense"}` returned `200 {"status": "accepted"}`. The
background task then routed the unknown trigger to `END` and wrote an audit
row saying "Completed Execution" with `confidence=0.99`. A caller could not
find out what happened to an event; a failure printed and returned `None`.

## Decision

- The raw body must verify against `WEBHOOK_SECRET` with HMAC-SHA256 in
  `X-Hub-Signature-256` — GitHub's own scheme, so a GitHub webhook works
  unchanged — or carry `X-API-Key`. With neither secret configured the route
  is open, which the preflight refuses in production.
- `trigger_type` is a `Literal`; `repo` matches `owner/name`; `commit_sha` is
  hex; the body is capped at 256 KB. Anything else is `422`, not "accepted".
- The response is `202` with an event id and the dry-run flag. `GET
  /events/{id}` returns the audit row: status, agents, the confidence the
  model reported (or `null`), errors, timestamps.
- Every run ends in exactly one of `completed`, `needs_human`, `no_route`,
  `failed`. Exceptions are recorded as `failed` with the exception type.

## Consequences

An operator can prove a delivery came from GitHub, can see that an event was
refused and why, and can see a failure. CI boots the server and asserts the
401, the 422, the 202, and the `needs_human` outcome of a manual event.

The body schema is this service's, not GitHub's native payload; a translator
in front is needed for raw GitHub events. The README says so.
