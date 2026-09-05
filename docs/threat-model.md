# Threat model

Scope: one FastAPI process receiving events and running specialist agents
that can, when explicitly enabled, comment on GitHub and change PagerDuty
incidents. An audit trail in SQLite or Postgres.

## What it holds

| Asset | Where | Why it matters |
|---|---|---|
| `GITHUB_TOKEN` | `.env` | Posts as the operator on every repository it can reach |
| `PAGERDUTY_API_KEY` | `.env` | Acknowledges and resolves incidents |
| `AWS_*` | `.env` | Cost Explorer read |
| Provider keys | `.env` | Billable |
| `WEBHOOK_SECRET` / `API_KEY` | `.env` | Gate the only inbound route |
| Event payloads and agent outputs | audit trail | May contain PR text and incident detail; secret-looking keys are redacted before storage |

## Threats

### T1 — Anyone starts a workflow *(was open)*

Reproduced: an unsigned, unkeyed request with an unknown trigger was
accepted. **Controls.** HMAC signature or API key, constant-time comparison;
production refuses to start with neither; triggers validated; body capped.

### T2 — The model acts on the wrong target *(was open)*

`pr_number` defaulted to 1 and `incident_id` to INC0001. **Controls.**
Missing identifiers are refusals recorded as `needs_human`; `ALLOWED_REPOS`
bounds which repositories a comment can land on; `DRY_RUN` (default) turns
writes into descriptions.

### T3 — An escalation resolves an incident *(was open)*

Any PagerDuty action other than `acknowledge` sent `status: resolved`.
**Controls.** Three named actions, schema-enforced; only `resolve` closes.

### T4 — Prompt injection through PR content

The review agent reads pull-request titles, bodies and diffs — text written
by whoever opened the PR — and holds a tool that posts comments. A PR that
instructs the model can shape what is posted. **Controls.** `DRY_RUN`,
`ALLOWED_REPOS`, a comment size cap, and the fact that the only write the
review agent holds is a comment on the same repository. **Residual.** A
misleading or hostile comment on an allowlisted repository is possible when
live; a human reads it. There is no approval step before posting.

### T5 — Fabricated evidence in the audit trail *(was open)*

Hardcoded CI logs and CVEs, and a fixed confidence of 0.99. **Controls.**
Unimplemented tools return `not_implemented`; confidence is recorded only
when the model reported one.

### T6 — Secrets in the image or the log

`COPY . .` would have baked a local `.env` into the image; the audit log
stored raw payloads. **Controls.** The image copies `*.py` only and runs as
uid 10001; payloads are redacted on secret-looking keys before storage.

### T7 — Supply chain

Sixteen unpinned packages, four of them imported by nothing after the
provider change. Everything is pinned; `pip-audit`, `bandit` and gitleaks run
in CI.

## Not addressed

- No queue, retry or concurrency limit: events run as background tasks in one
  process and are lost if it dies mid-run.
- No per-caller rate limit on the webhook.
- No human approval step before a live write; `DRY_RUN` is the control.
- Nothing has been run against a model, GitHub, PagerDuty or AWS in this
  repository; the live paths are tested with fakes.
