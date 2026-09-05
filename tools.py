"""
What the agents can do to the outside world.

The previous tools, by kind:

* Two GitHub tools that read any repository and commented on any pull request
  the token could reach, on any model's say-so, with no allowlist.
* A PagerDuty tool whose status mapping was ``"acknowledged" if action ==
  "acknowledge" else "resolved"`` -- so an agent told to "escalate via note"
  and calling ``action="escalate"`` **resolved the incident**.
* Three tools that returned hardcoded fiction: a CI log with
  ``ModuleNotFoundError: No module named 'pydantic'`` for every pipeline id, a
  security scan with ``CVE-2024-xyz`` for every repository, and
  "Successfully updated {doc_type} documentation." for a documentation update
  that did nothing. The agents reasoned from that fiction and the audit log
  recorded the results as work done.

Now:

* ``DRY_RUN`` (default on) turns every write into a description of what would
  have happened. ``ALLOWED_REPOS`` (default empty) is an exact allowlist for
  the GitHub tools.
* PagerDuty actions are an explicit set: ``acknowledge``, ``resolve``,
  ``note``. Anything else is refused. ``resolve`` is the only one that closes
  an incident.
* A tool with no implementation says ``not_implemented`` and describes what a
  real implementation would need. It does not make something up.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Literal

import httpx
from crewai.tools import BaseTool
from pydantic import BaseModel, Field

from config import settings

logger = logging.getLogger("devops_os.tools")

MAX_DIFF_CHARS = 60_000
PAGERDUTY_API = "https://api.pagerduty.com"
REPO_PATTERN = r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$"


def _repo_allowed(repo: str) -> str | None:
    """None when allowed; otherwise the refusal message."""
    if not settings.allowed_repos:
        return "refused: ALLOWED_REPOS is empty, so no repository may be read or written."
    if repo.strip().lower() not in settings.allowed_repos:
        return f"refused: {repo} is not in ALLOWED_REPOS."
    return None


def not_implemented(tool: str, would_need: str) -> str:
    return f"not_implemented: {tool} has no live integration. A real one would need {would_need}. No data was produced."


# -- GitHub -------------------------------------------------------------------


class PRRef(BaseModel):
    repo: str = Field(pattern=REPO_PATTERN, description="owner/name")
    pr_number: int = Field(ge=1)


class GithubPRFetchTool(BaseTool):
    name: str = "fetch_github_pr"
    description: str = "Fetch a pull request's title, body and file diffs. Input: repo (owner/name), pr_number."
    args_schema: type[BaseModel] = PRRef

    def _run(self, repo: str, pr_number: int) -> str:
        refusal = _repo_allowed(repo)
        if refusal:
            return refusal
        token = settings.GITHUB_TOKEN.strip()
        if not token:
            return "refused: GITHUB_TOKEN is not set."
        try:
            from github import Github

            pr = Github(token).get_repo(repo).get_pull(pr_number)
            parts = [f"PR #{pr.number} - {pr.title}", pr.body or "(no description)", "", "=== DIFFS ==="]
            for file in pr.get_files():
                patch = file.patch if file.patch is not None else "(no textual diff: binary or too large)"
                parts.append(f"File: {file.filename}\nStatus: {file.status}\nChanges:\n{patch}")
            text = "\n".join(parts)
            if len(text) > MAX_DIFF_CHARS:
                text = text[:MAX_DIFF_CHARS] + f"\n... truncated at {MAX_DIFF_CHARS} characters"
            return text
        except Exception as error:
            logger.exception("fetch_github_pr failed for %s#%s", repo, pr_number)
            return f"error: could not fetch the pull request ({type(error).__name__})."


class PRComment(PRRef):
    comment: str = Field(min_length=1)


class GithubCommentTool(BaseTool):
    name: str = "post_github_pr_comment"
    description: str = "Post a comment on a pull request. Input: repo (owner/name), pr_number, comment."
    args_schema: type[BaseModel] = PRComment

    def _run(self, repo: str, pr_number: int, comment: str) -> str:
        refusal = _repo_allowed(repo)
        if refusal:
            return refusal
        if len(comment) > settings.MAX_COMMENT_CHARS:
            comment = comment[: settings.MAX_COMMENT_CHARS] + "\n\n(truncated)"
        if settings.DRY_RUN:
            logger.info("DRY RUN: would comment on %s#%s (%d chars)", repo, pr_number, len(comment))
            return f"dry_run: would post a {len(comment)}-character comment on {repo}#{pr_number}. Nothing was posted."
        token = settings.GITHUB_TOKEN.strip()
        if not token:
            return "refused: GITHUB_TOKEN is not set."
        try:
            from github import Github

            Github(token).get_repo(repo).get_pull(pr_number).create_issue_comment(comment)
            return f"posted: comment on {repo}#{pr_number}."
        except Exception as error:
            logger.exception("post_github_pr_comment failed for %s#%s", repo, pr_number)
            return f"error: could not post the comment ({type(error).__name__})."


# -- CI -------------------------------------------------------------------------


class PipelineRef(BaseModel):
    pipeline_id: str = Field(min_length=1)


class FetchCILogsTool(BaseTool):
    name: str = "fetch_ci_logs"
    description: str = "Fetch the logs of a CI run. Not implemented: reports so instead of inventing a log."
    args_schema: type[BaseModel] = PipelineRef

    def _run(self, pipeline_id: str) -> str:
        return not_implemented(
            "fetch_ci_logs",
            "a CI provider API (GitHub Actions run logs, Jenkins console output) and a token for it",
        )


# -- AWS -------------------------------------------------------------------------


class NoArgs(BaseModel):
    pass


class AWSCostExplorerTool(BaseTool):
    name: str = "aws_cost_last_30_days"
    description: str = "Unblended AWS cost for the last 30 days from Cost Explorer."
    args_schema: type[BaseModel] = NoArgs

    def _run(self) -> str:
        if not settings.AWS_ACCESS_KEY_ID.strip() or not settings.AWS_SECRET_ACCESS_KEY.strip():
            return "refused: AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY are not set. No cost data was produced."
        try:
            import boto3

            client = boto3.client(
                "ce",
                aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
                aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
                region_name=settings.AWS_DEFAULT_REGION,
            )
            end = datetime.now(UTC).date()
            start = end - timedelta(days=30)
            response = client.get_cost_and_usage(
                TimePeriod={"Start": start.isoformat(), "End": end.isoformat()},
                Granularity="MONTHLY",
                Metrics=["UnblendedCost"],
            )
            lines = ["AWS unblended cost, last 30 days:"]
            for period in response.get("ResultsByTime", []):
                total = period["Total"]["UnblendedCost"]
                span = period["TimePeriod"]
                lines.append(f"{span['Start']} to {span['End']}: {total['Amount']} {total['Unit']}")
            return "\n".join(lines)
        except Exception as error:
            logger.exception("aws_cost_last_30_days failed")
            return f"error: Cost Explorer call failed ({type(error).__name__})."


# -- PagerDuty ---------------------------------------------------------------------

PagerDutyAction = Literal["acknowledge", "resolve", "note"]
STATUS_FOR_ACTION = {"acknowledge": "acknowledged", "resolve": "resolved"}


class PagerDutyArgs(BaseModel):
    incident_id: str = Field(min_length=1)
    action: PagerDutyAction
    note: str = ""


class PagerDutyAlertTool(BaseTool):
    name: str = "pagerduty_incident"
    description: str = (
        "Act on a PagerDuty incident. action is one of: acknowledge, resolve, note. "
        "Only 'resolve' closes an incident. Use 'note' to escalate or record findings."
    )
    args_schema: type[BaseModel] = PagerDutyArgs

    def _run(self, incident_id: str, action: str, note: str = "") -> str:
        if action not in ("acknowledge", "resolve", "note"):
            return f"refused: unknown action {action!r}; use acknowledge, resolve or note."
        if settings.DRY_RUN:
            logger.info("DRY RUN: would %s incident %s", action, incident_id)
            return (
                f"dry_run: would {action} incident {incident_id}"
                + (f" with note ({len(note)} chars)" if note else "")
                + ". Nothing was changed."
            )
        key = settings.PAGERDUTY_API_KEY.strip()
        if not key:
            return "refused: PAGERDUTY_API_KEY is not set."
        if not settings.PAGERDUTY_FROM_EMAIL.strip():
            return "refused: PAGERDUTY_FROM_EMAIL is not set; PagerDuty requires it."
        headers = {
            "Authorization": f"Token token={key}",
            "Accept": "application/vnd.pagerduty+json;version=2",
            "Content-Type": "application/json",
            "From": settings.PAGERDUTY_FROM_EMAIL,
        }
        url = f"{PAGERDUTY_API}/incidents/{incident_id}"
        try:
            if action in STATUS_FOR_ACTION:
                body = {"incident": {"type": "incident_reference", "status": STATUS_FOR_ACTION[action]}}
                httpx.put(url, headers=headers, json=body, timeout=10.0).raise_for_status()
            if note:
                httpx.post(
                    f"{url}/notes", headers=headers, json={"note": {"content": note}}, timeout=10.0
                ).raise_for_status()
            return f"done: {action} on incident {incident_id}."
        except Exception as error:
            logger.exception("pagerduty_incident %s failed for %s", action, incident_id)
            return f"error: PagerDuty call failed ({type(error).__name__})."


# -- documentation and security: not implemented ------------------------------------


class DocArgs(BaseModel):
    doc_type: str = Field(min_length=1)
    content: str = Field(min_length=1)


class DocumentationUpdateTool(BaseTool):
    name: str = "update_documentation"
    description: str = "Update documentation. Not implemented: reports so instead of claiming success."
    args_schema: type[BaseModel] = DocArgs

    def _run(self, doc_type: str, content: str) -> str:
        return not_implemented(
            "update_documentation", "a target (a docs repository via PR, Confluence, or Notion) and credentials for it"
        )


class RepoRef(BaseModel):
    repo: str = Field(pattern=REPO_PATTERN)


class SecurityScanTool(BaseTool):
    name: str = "security_scan"
    description: str = (
        "Run dependency and static security scans. Not implemented: reports so instead of inventing findings."
    )
    args_schema: type[BaseModel] = RepoRef

    def _run(self, repo: str) -> str:
        return not_implemented(
            "security_scan", "a checkout of the repository and scanners such as pip-audit, npm audit or semgrep"
        )


github_pr_tool = GithubPRFetchTool()
github_comment_tool = GithubCommentTool()
fetch_ci_logs_tool = FetchCILogsTool()
aws_cost_tool = AWSCostExplorerTool()
pagerduty_tool = PagerDutyAlertTool()
documentation_tool = DocumentationUpdateTool()
security_scan_tool = SecurityScanTool()
