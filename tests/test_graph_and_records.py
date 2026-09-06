"""
Routing, refusals, the audit trail, settings and the prompt helper.

Reproduced on the original: ``pr_number`` defaulted to 1 and ``incident_id``
to ``INC0001``; the repo fallback never ran because the key existed as None;
the router doubled the message history under ``add_messages``;
``confidence=0.99`` was written for every run; ``build_agent_prompt`` joined
with a literal backslash-n.
"""

from __future__ import annotations

import pytest
from langgraph.graph import END

import agent_graph
from agent_graph import (
    ROUTES,
    TRIGGERS,
    base_state,
    orchestrator_node,
    parse_output,
    reported_confidence,
    run_devops_workflow,
)
from config import Settings, settings
from database import get_run, redact
from devops_agent_prompts import GUARDRAILS_PROMPT, build_agent_prompt


class TestRouting:
    def test_every_trigger_but_manual_has_a_node(self):
        assert set(ROUTES) == set(TRIGGERS) - {"manual"}

    @pytest.mark.parametrize("trigger,node", ROUTES.items())
    def test_known_triggers_route(self, trigger, node):
        assert orchestrator_node(base_state("e", trigger, {}, None))["current_agent"] == node

    def test_manual_is_left_for_a_human(self):
        out = orchestrator_node(base_state("e", "manual", {}, None))
        assert out["current_agent"] == END
        assert out["requires_human"] is True

    def test_an_unknown_trigger_does_not_run_anything(self):
        out = orchestrator_node(base_state("e", "nonsense", {}, None))
        assert out["current_agent"] == END
        assert "unknown trigger_type" in out["human_approval_reason"]

    def test_the_router_returns_only_its_new_message(self):
        """Returning the whole list under add_messages doubled the history."""
        state = base_state("e", "pr_opened", {}, None)
        state["messages"] = ["earlier"]
        out = orchestrator_node(state)
        assert len(out["messages"]) == 1

    def test_a_full_run_holds_exactly_two_messages(self, scripted_crew):
        scripted_crew("{}")
        results = agent_graph.get_graph().invoke(base_state("e", "pr_opened", {"pr_number": 3}, "octo/repo"))
        assert len(results["messages"]) == 2


class TestNoGuessedIdentifiers:
    def test_a_pr_event_without_a_number_runs_nothing(self, scripted_crew):
        calls = scripted_crew("{}")
        results = agent_graph.get_graph().invoke(base_state("e", "pr_opened", {}, "octo/repo"))
        assert results["requires_human"] is True
        assert calls == []

    @pytest.mark.parametrize("bad", [0, -1, "7", None])
    def test_a_non_positive_or_non_integer_number_is_refused(self, scripted_crew, bad):
        calls = scripted_crew("{}")
        results = agent_graph.get_graph().invoke(base_state("e", "pr_opened", {"pr_number": bad}, "octo/repo"))
        assert results["requires_human"] is True and calls == []

    def test_a_pagerduty_event_without_an_incident_runs_nothing(self, scripted_crew):
        calls = scripted_crew("{}")
        results = agent_graph.get_graph().invoke(base_state("e", "pagerduty", {}, None))
        assert results["requires_human"] is True
        assert "incident_id" in results["human_approval_reason"]
        assert calls == []

    def test_the_repo_falls_back_to_the_payload(self, scripted_crew):
        """state['repo'] exists as None; the old .get(key, default) never fell back."""
        calls = scripted_crew("{}")
        agent_graph.get_graph().invoke(base_state("e", "pr_merged", {"repo": "octo/repo"}, None))
        assert calls and calls[0][0] == "documentation"

    def test_a_ci_event_needs_a_run_id(self, scripted_crew):
        calls = scripted_crew("{}")
        results = agent_graph.get_graph().invoke(base_state("e", "ci_failed", {}, "octo/repo"))
        assert results["requires_human"] is True and calls == []


class TestConfidence:
    @pytest.mark.parametrize(
        "value,expected", [(0.8, 0.8), (1, 1.0), (0, 0.0), (1.5, None), (-0.1, None), ("high", None), (True, None)]
    )
    def test_only_a_reported_number_in_range_counts(self, value, expected):
        assert reported_confidence({"confidence": value}) == expected

    def test_absent_is_none(self):
        assert reported_confidence({}) is None

    def test_the_audit_row_carries_the_reported_value_or_nothing(self, scripted_crew):
        scripted_crew('{"confidence": 0.6}')
        run_devops_workflow("conf-1", {"trigger_type": "pr_opened", "repo": "octo/repo", "payload": {"pr_number": 1}})
        assert get_run("conf-1")["confidence"] == 0.6
        scripted_crew('{"decision": "APPROVE"}')
        run_devops_workflow("conf-2", {"trigger_type": "pr_opened", "repo": "octo/repo", "payload": {"pr_number": 1}})
        assert get_run("conf-2")["confidence"] is None


class TestAuditTrail:
    def test_a_completed_run_is_recorded(self, scripted_crew):
        scripted_crew('{"decision": "APPROVE"}')
        out = run_devops_workflow(
            "run-1", {"trigger_type": "pr_opened", "repo": "octo/repo", "payload": {"pr_number": 2}}
        )
        assert out["status"] == "completed"
        row = get_run("run-1")
        assert row["status"] == "completed" and row["agents"] == ["CodeReviewAgent"]
        assert row["finished_at"] is not None

    def test_a_no_route_run_is_not_called_completed(self, scripted_crew):
        scripted_crew("{}")
        out = run_devops_workflow("run-2", {"trigger_type": "manual"})
        assert out["status"] == "needs_human"
        assert get_run("run-2")["status"] == "needs_human"

    def test_a_crashing_specialist_is_recorded_as_failed(self, scripted_crew):
        scripted_crew(raise_error=RuntimeError("boom"))
        out = run_devops_workflow("run-3", {"trigger_type": "scheduled_infra"})
        assert out["status"] == "failed"
        assert get_run("run-3")["status"] == "failed"

    def test_secrets_in_the_payload_are_redacted(self):
        assert redact({"github_token": "ghp_x", "nested": {"api_key": "k", "fine": 1}}) == {
            "github_token": "[redacted]",
            "nested": {"api_key": "[redacted]", "fine": 1},
        }

    def test_parse_output_tolerates_fences_and_prose(self):
        assert parse_output('```json\n{"a": 1}\n```') == {"a": 1}
        assert parse_output("no json here")["raw_output"] == "no json here"
        assert parse_output("[1, 2]")["raw_output"] == [1, 2]


class TestSettings:
    def build(self, **kw):
        base = {"_env_file": None}
        base.update(kw)
        return Settings(**base)

    def test_dry_run_is_on_by_default(self, monkeypatch):
        monkeypatch.delenv("DRY_RUN", raising=False)
        assert self.build().DRY_RUN is True

    @pytest.mark.parametrize("value", ["", "  "])
    def test_a_blank_dry_run_keeps_the_safe_default(self, monkeypatch, value):
        monkeypatch.setenv("DRY_RUN", value)
        assert self.build().DRY_RUN is True

    def test_production_without_any_inbound_secret_is_a_problem(self):
        problems = self.build(ENVIRONMENT="production", WEBHOOK_SECRET="", API_KEY="").problems()
        assert any("WEBHOOK_SECRET" in p for p in problems)

    def test_live_writes_with_an_empty_allowlist_is_a_problem(self):
        problems = self.build(DRY_RUN=False, GITHUB_TOKEN="t", ALLOWED_REPOS="").problems()
        assert any("ALLOWED_REPOS" in p for p in problems)

    def test_allowed_repos_are_lowercased_and_trimmed(self):
        assert self.build(ALLOWED_REPOS="Octo/Repo , other/x").allowed_repos == {"octo/repo", "other/x"}

    def test_a_heroku_style_postgres_url_is_normalised(self):
        assert self.build(DATABASE_URL="postgres://u:p@h/d").DATABASE_URL.startswith("postgresql://")

    def test_the_active_settings_default_to_dry_run(self):
        assert settings.DRY_RUN is True


class TestPromptHelper:
    def test_guardrails_are_joined_with_a_real_newline(self):
        joined = build_agent_prompt("BASE")
        assert "\\n" not in joined
        assert joined.startswith("BASE\n\n")
        assert GUARDRAILS_PROMPT.strip() in joined

    def test_guardrails_can_be_left_out(self):
        assert build_agent_prompt("BASE", include_guardrails=False) == "BASE"
