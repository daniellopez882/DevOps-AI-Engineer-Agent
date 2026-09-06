# ADR 0003 — Missing identifiers are refusals, not defaults; tools without an integration say so

**Status:** accepted

## Context

```python
pr_number = payload.get("pr_number", 1)
incident_id = payload.get("incident_id", "INC0001")
```

A pull-request event that omitted the number reviewed — and, live, commented
on — PR #1. A PagerDuty event that omitted the incident acted on INC0001.
`state.get("repo", payload.get("repo"))` never fell back, because the base
state set `repo` to `None` and `.get` returns an existing `None`.

Three tools returned fiction: a CI log with `ModuleNotFoundError: No module
named 'pydantic'` for every pipeline, a scan with `CVE-2024-xyz` for every
repository, and "Successfully updated {doc_type} documentation." for an
update that did nothing. The agents reasoned from it and the audit log
recorded the conclusions.

## Decision

A node that lacks the identifier it needs does not run its specialist. It
sets `requires_human` with a reason naming the field, and the run is recorded
as `needs_human`. Tests assert the specialist was never called.

The repo is read from the state value, falling back to the payload value —
by value, not by key presence.

A tool with no live integration returns `not_implemented: <tool> has no live
integration. A real one would need <what>. No data was produced.` The task
descriptions tell the agents to report `not_implemented` results as such.

`confidence` in the audit row is the number the model reported, if it
reported one in `[0, 1]`; otherwise `null`. Nothing writes a fixed value.

## Consequences

Fewer runs "complete". That is the point: a run that guessed PR #1 was not a
completed review, and an audit row that says `needs_human: code review needs
repo and pr_number` is worth more than one that says `Completed Execution
0.99`.
