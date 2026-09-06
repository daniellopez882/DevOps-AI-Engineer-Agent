"""
What the tools do to the outside world.

Reproduced on the original: ``fetch_ci_logs`` returned the same
``ModuleNotFoundError`` log for any pipeline id; ``security_scan`` returned
``CVE-2024-xyz`` for any repository; ``update_documentation`` answered
"Successfully updated"; and the PagerDuty tool sent ``status: resolved`` for
``action="escalate"``.
"""

from __future__ import annotations

import pytest

import tools
from config import settings


@pytest.fixture
def live(monkeypatch):
    """DRY_RUN off, with the credentials the tools check for."""
    monkeypatch.setattr(settings, "DRY_RUN", False)
    monkeypatch.setattr(settings, "GITHUB_TOKEN", "ghp_test")
    monkeypatch.setattr(settings, "PAGERDUTY_API_KEY", "pd_test")
    monkeypatch.setattr(settings, "PAGERDUTY_FROM_EMAIL", "oncall@example.com")


@pytest.fixture
def pagerduty_calls(monkeypatch):
    calls: list[tuple[str, str, dict]] = []

    class Resp:
        def raise_for_status(self):
            pass

    def put(url, headers=None, json=None, timeout=None):
        calls.append(("PUT", url, json))
        return Resp()

    def post(url, headers=None, json=None, timeout=None):
        calls.append(("POST", url, json))
        return Resp()

    monkeypatch.setattr(tools.httpx, "put", put)
    monkeypatch.setattr(tools.httpx, "post", post)
    return calls


class TestHonestStubs:
    def test_ci_logs_are_not_invented(self):
        out = tools.FetchCILogsTool()._run("run-123")
        assert out.startswith("not_implemented")
        assert "pydantic" not in out

    def test_security_findings_are_not_invented(self):
        out = tools.SecurityScanTool()._run("octo/repo")
        assert out.startswith("not_implemented")
        assert "CVE" not in out

    def test_documentation_success_is_not_claimed(self):
        out = tools.DocumentationUpdateTool()._run("README", "text")
        assert out.startswith("not_implemented")
        assert "Successfully" not in out

    def test_aws_without_credentials_produces_no_numbers(self):
        out = tools.AWSCostExplorerTool()._run()
        assert out.startswith("refused")
        assert not any(ch.isdigit() for ch in out.split(":", 1)[1] if ch not in "_")


class TestPagerDutyActions:
    def test_acknowledge_sets_acknowledged(self, live, pagerduty_calls):
        tools.PagerDutyAlertTool()._run("INC1", "acknowledge")
        assert pagerduty_calls[0][2]["incident"]["status"] == "acknowledged"

    def test_resolve_is_the_only_action_that_resolves(self, live, pagerduty_calls):
        tools.PagerDutyAlertTool()._run("INC1", "resolve")
        assert pagerduty_calls[0][2]["incident"]["status"] == "resolved"

    def test_a_note_changes_no_status(self, live, pagerduty_calls):
        tools.PagerDutyAlertTool()._run("INC1", "note", "cannot fix, paging a human")
        assert [c[0] for c in pagerduty_calls] == ["POST"]
        assert pagerduty_calls[0][1].endswith("/notes")

    def test_escalate_does_not_resolve(self, live, pagerduty_calls):
        """The old mapping: anything but 'acknowledge' -> resolved."""
        out = tools.PagerDutyAlertTool()._run("INC1", "escalate", "help")
        assert out.startswith("refused")
        assert pagerduty_calls == []

    def test_dry_run_changes_nothing(self, pagerduty_calls, monkeypatch):
        monkeypatch.setattr(settings, "PAGERDUTY_API_KEY", "pd_test")
        out = tools.PagerDutyAlertTool()._run("INC1", "resolve")
        assert out.startswith("dry_run")
        assert pagerduty_calls == []

    def test_a_from_email_is_required(self, live, pagerduty_calls, monkeypatch):
        monkeypatch.setattr(settings, "PAGERDUTY_FROM_EMAIL", "")
        assert tools.PagerDutyAlertTool()._run("INC1", "acknowledge").startswith("refused")
        assert pagerduty_calls == []

    def test_the_schema_only_admits_the_three_actions(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            tools.PagerDutyArgs(incident_id="INC1", action="escalate")


class TestGitHubGuards:
    def test_a_repo_off_the_allowlist_is_refused_before_any_call(self, live, monkeypatch):
        def explode(*a, **k):
            raise AssertionError("GitHub was called")

        monkeypatch.setitem(__import__("sys").modules, "github", type("M", (), {"Github": explode}))
        assert tools.GithubCommentTool()._run("evil/repo", 1, "hi").startswith("refused")
        assert tools.GithubPRFetchTool()._run("evil/repo", 1).startswith("refused")

    def test_the_allowlist_is_case_insensitive(self, live, monkeypatch):
        monkeypatch.setattr(settings, "DRY_RUN", True)
        assert tools.GithubCommentTool()._run("OCTO/other", 1, "hi").startswith("dry_run")

    def test_an_empty_allowlist_allows_nothing(self, live, monkeypatch):
        monkeypatch.setattr(settings, "ALLOWED_REPOS", "")
        assert "ALLOWED_REPOS is empty" in tools.GithubCommentTool()._run("octo/repo", 1, "hi")

    def test_dry_run_posts_nothing(self, monkeypatch):
        def explode(*a, **k):
            raise AssertionError("GitHub was called")

        monkeypatch.setitem(__import__("sys").modules, "github", type("M", (), {"Github": explode}))
        out = tools.GithubCommentTool()._run("octo/repo", 1, "looks good")
        assert out.startswith("dry_run")
        assert "10-character" in out

    def test_a_comment_is_capped(self, monkeypatch):
        monkeypatch.setattr(settings, "MAX_COMMENT_CHARS", 100)
        out = tools.GithubCommentTool()._run("octo/repo", 1, "x" * 5000)
        assert "112-character" in out or "(truncated)" in out or "-character" in out

    def test_a_binary_file_has_no_patch(self, live, monkeypatch):
        class File:
            filename = "logo.png"
            status = "added"
            patch = None

        class PR:
            number = 1
            title = "t"
            body = None

            def get_files(self):
                return [File()]

        class Repo:
            def get_pull(self, n):
                return PR()

        class GH:
            def __init__(self, token):
                pass

            def get_repo(self, name):
                return Repo()

        monkeypatch.setitem(__import__("sys").modules, "github", type("M", (), {"Github": GH}))
        out = tools.GithubPRFetchTool()._run("octo/repo", 1)
        assert "no textual diff" in out
        assert "None" not in out.split("Changes:")[1]
