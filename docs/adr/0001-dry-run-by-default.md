# ADR 0001 — Dry run is the default; writes need an allowlist

**Status:** accepted

## Context

Two of the seven tools change the world: a GitHub pull-request comment and a
PagerDuty status change. Both ran whenever a model asked, on any repository
or incident the credentials could reach. The webhook that started the run
accepted any caller (ADR 0002), so the chain from "anyone on the network" to
"an incident was resolved" had no gate in it.

## Decision

`DRY_RUN` is a setting that defaults to **on**. When on, a write returns a
sentence describing what would have happened (`dry_run: would post a
612-character comment on octo/repo#42. Nothing was posted.`) and the audit
row records `dry_run: true`. A blank `DRY_RUN=` keeps the default rather
than silently enabling writes.

`ALLOWED_REPOS` is an exact, case-insensitive `owner/name` list. Empty means
no repository. Both GitHub tools check it before any network call, in dry run
or not. Turning dry run off with a token configured and an empty allowlist is
a configuration problem the preflight reports.

PagerDuty actions are an explicit set — `acknowledge`, `resolve`, `note` —
enforced twice: in the tool's pydantic schema and again in `_run`. Only
`resolve` closes an incident; `note` is how an agent escalates.

## Consequences

The first live event an operator sends does nothing external. Making it do
something is two deliberate settings. The tests exercise the live path with a
fake GitHub module and a captured `httpx`, so the mapping from action to
status is asserted, not assumed.
