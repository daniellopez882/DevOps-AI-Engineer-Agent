"""
The LangGraph workflow: one router, six specialists, one audit row per run.

What the previous graph did that mattered, in order:

* ``pr_number = payload.get("pr_number", 1)`` and
  ``incident_id = payload.get("incident_id", "INC0001")``. A pull-request
  event without a number reviewed -- and commented on -- PR #1. A PagerDuty
  event without an incident id acted on INC0001. A missing identifier is now
  a refusal that asks for a human, not a default.
* ``state.get("repo", payload.get("repo", ...))`` -- the fallback never ran,
  because the key exists (as ``None``) in the base state.
* The router appended to ``state["messages"]`` in place and returned the same
  list. With the ``add_messages`` reducer that is appended again, so every
  step doubled the history.
* ``confidence=0.99`` was written to the audit log for every run.
* An unknown trigger routed to ``END`` and was logged as "Completed
  Execution" with that confidence.
* Exceptions were printed and swallowed; the run vanished from the record.

The specialists still run through crewai. ``run_crew`` is a module function
so the tests can replace it with a scripted one.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import UTC, datetime
from functools import lru_cache
from typing import Annotated, Any, TypedDict

from langchain_core.messages import AIMessage
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages

from config import settings
from crew_agents import DevOpsOSCrew
from database import finish_run, start_run
from tasks import (
    get_ci_monitor_task,
    get_code_review_task,
    get_documentation_task,
    get_incident_responder_task,
    get_infra_optimization_task,
    get_security_audit_task,
)

logger = logging.getLogger("devops_os.graph")

# trigger -> node
ROUTES: dict[str, str] = {
    "pr_opened": "code_review_agent",
    "ci_failed": "ci_monitor_agent",
    "scheduled_infra": "infra_optimizer_agent",
    "pagerduty": "incident_responder_agent",
    "pr_merged": "documentation_agent",
    "scheduled_security": "security_audit_agent",
}
# A manual event has no automatic route: it is recorded and left for a human.
TRIGGERS: tuple[str, ...] = (*ROUTES, "manual")

OUTPUT_KEYS = ("code_review", "ci_diagnosis", "infra_report", "incident_report", "docs_update", "security_report")


class DevOpsAgentState(TypedDict, total=False):
    messages: Annotated[list, add_messages]
    event_id: str
    trigger_type: str
    payload: dict
    repo: str | None
    branch: str | None
    commit_sha: str | None

    code_review: dict | None
    ci_diagnosis: dict | None
    infra_report: dict | None
    incident_report: dict | None
    docs_update: dict | None
    security_report: dict | None

    priority: str
    current_agent: str | None
    requires_human: bool
    human_approval_reason: str | None
    confidence: float | None

    errors: list[str]
    completed_agents: list[str]
    started_at: str
    run_duration_seconds: float


def base_state(event_id: str, trigger_type: str, payload: dict | None, repo: str | None) -> DevOpsAgentState:
    return {
        "messages": [],
        "event_id": event_id,
        "trigger_type": trigger_type,
        "payload": payload or {},
        "repo": repo,
        "branch": None,
        "commit_sha": None,
        "priority": "P1" if trigger_type == "pagerduty" else "P3",
        "current_agent": None,
        "requires_human": False,
        "human_approval_reason": None,
        "confidence": None,
        "errors": [],
        "completed_agents": [],
        "started_at": datetime.now(UTC).isoformat(),
        "run_duration_seconds": 0.0,
    }


# -- helpers ----------------------------------------------------------------------


def parse_output(raw: str) -> dict:
    """The JSON object in a model reply, or ``{"raw_output": ...}``."""
    text = (raw or "").strip()
    for fence in ("```json", "```"):
        text = text.replace(fence, "")
    text = text.strip()
    try:
        parsed = json.loads(text)
    except (ValueError, TypeError):
        return {"raw_output": (raw or "")[:4000]}
    return parsed if isinstance(parsed, dict) else {"raw_output": parsed}


def reported_confidence(output: dict) -> float | None:
    """The confidence the model reported, if it reported one in [0, 1]. Never invented."""
    value = output.get("confidence")
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value) if 0.0 <= float(value) <= 1.0 else None


def run_crew(agent: Any, task: Any) -> str:
    """Run one agent on one task and return the raw text. Replaced by the tests."""
    from crewai import Crew

    result = Crew(agents=[agent], tasks=[task], verbose=False).kickoff()
    raw = getattr(result, "raw", None)
    return raw if isinstance(raw, str) else str(result)


def _repo(state: DevOpsAgentState) -> str | None:
    # state["repo"] exists as None in the base state; `.get(key, default)`
    # returns that None and never falls back. Check the value, not the key.
    return state.get("repo") or (state.get("payload") or {}).get("repo")


def _needs_human(state: DevOpsAgentState, reason: str) -> dict:
    logger.warning("[%s] %s", state.get("event_id"), reason)
    return {
        "requires_human": True,
        "human_approval_reason": reason,
        "errors": [*state.get("errors", []), reason],
        "messages": [AIMessage(content=reason)],
    }


def _record(state: DevOpsAgentState, key: str, agent_name: str, raw: str) -> dict:
    output = parse_output(raw)
    return {
        key: output,
        "confidence": reported_confidence(output),
        "completed_agents": [*state.get("completed_agents", []), agent_name],
        "messages": [AIMessage(content=f"{agent_name} finished")],
    }


# -- nodes ------------------------------------------------------------------------


def orchestrator_node(state: DevOpsAgentState) -> dict:
    trigger = state.get("trigger_type", "manual")
    node = ROUTES.get(trigger)
    if node is None:
        reason = (
            "manual events are recorded for a human; nothing runs automatically"
            if trigger == "manual"
            else f"unknown trigger_type {trigger!r}; nothing runs"
        )
        return {"current_agent": END, **_needs_human(state, reason)}
    # Return only the new message: the add_messages reducer appends it.
    return {"current_agent": node, "messages": [AIMessage(content=f"routed {trigger} to {node}")]}


def code_review_agent_node(state: DevOpsAgentState) -> dict:
    repo = _repo(state)
    pr_number = (state.get("payload") or {}).get("pr_number")
    if not repo or not isinstance(pr_number, int) or pr_number < 1:
        return _needs_human(state, "code review needs repo and pr_number; refusing to guess a pull request")
    agent = DevOpsOSCrew().create_code_review_agent()
    raw = run_crew(agent, get_code_review_task(agent, repo, pr_number))
    return _record(state, "code_review", "CodeReviewAgent", raw)


def ci_monitor_agent_node(state: DevOpsAgentState) -> dict:
    repo = _repo(state)
    run_id = (state.get("payload") or {}).get("run_id")
    if not repo or not run_id:
        return _needs_human(state, "CI diagnosis needs repo and run_id")
    agent = DevOpsOSCrew().create_ci_monitor_agent()
    raw = run_crew(agent, get_ci_monitor_task(agent, repo, str(run_id)))
    return _record(state, "ci_diagnosis", "CIMonitorAgent", raw)


def infra_optimizer_agent_node(state: DevOpsAgentState) -> dict:
    agent = DevOpsOSCrew().create_infra_optimizer_agent()
    raw = run_crew(agent, get_infra_optimization_task(agent))
    return _record(state, "infra_report", "InfraOptimizerAgent", raw)


def incident_responder_agent_node(state: DevOpsAgentState) -> dict:
    incident_id = (state.get("payload") or {}).get("incident_id")
    if not incident_id:
        return _needs_human(state, "incident response needs incident_id; refusing to act on a guessed incident")
    agent = DevOpsOSCrew().create_incident_responder_agent()
    raw = run_crew(agent, get_incident_responder_task(agent, str(incident_id)))
    return _record(state, "incident_report", "IncidentResponder", raw)


def documentation_agent_node(state: DevOpsAgentState) -> dict:
    repo = _repo(state)
    if not repo:
        return _needs_human(state, "documentation update needs repo")
    agent = DevOpsOSCrew().create_documentation_agent()
    raw = run_crew(agent, get_documentation_task(agent, repo))
    return _record(state, "docs_update", "DocumentationAgent", raw)


def security_audit_agent_node(state: DevOpsAgentState) -> dict:
    repo = _repo(state)
    if not repo:
        return _needs_human(state, "security audit needs repo")
    agent = DevOpsOSCrew().create_security_audit_agent()
    raw = run_crew(agent, get_security_audit_task(agent, repo))
    return _record(state, "security_report", "SecurityAuditAgent", raw)


# -- graph ------------------------------------------------------------------------


def build_graph():
    workflow = StateGraph(DevOpsAgentState)
    workflow.add_node("orchestrator", orchestrator_node)
    workflow.add_node("code_review_agent", code_review_agent_node)
    workflow.add_node("ci_monitor_agent", ci_monitor_agent_node)
    workflow.add_node("infra_optimizer_agent", infra_optimizer_agent_node)
    workflow.add_node("incident_responder_agent", incident_responder_agent_node)
    workflow.add_node("documentation_agent", documentation_agent_node)
    workflow.add_node("security_audit_agent", security_audit_agent_node)

    workflow.set_entry_point("orchestrator")
    workflow.add_conditional_edges(
        "orchestrator",
        lambda state: state["current_agent"],
        {**{node: node for node in ROUTES.values()}, END: END},
    )
    for node in ROUTES.values():
        workflow.add_edge(node, END)
    return workflow.compile()


@lru_cache(maxsize=1)
def get_graph():
    return build_graph()


def outcome(results: DevOpsAgentState) -> str:
    if results.get("requires_human"):
        return "needs_human"
    if not results.get("completed_agents"):
        return "no_route"
    return "completed"


def run_devops_workflow(event_id: str, event: dict) -> dict:
    """
    Run one event through the graph and record it.

    Every path writes a final audit row: completed, needs_human, no_route or
    failed. The previous version printed exceptions and returned None, so a
    failed run left no trace.
    """
    trigger = event.get("trigger_type", "manual")
    repo = event.get("repo")
    payload = event.get("payload") or {}
    start_run(event_id, trigger, repo, event)
    started = time.monotonic()
    logger.info("[%s] starting %s (dry_run=%s)", event_id, trigger, settings.DRY_RUN)

    try:
        results = get_graph().invoke(base_state(event_id, trigger, payload, repo))
    except Exception as error:
        logger.exception("[%s] workflow failed", event_id)
        finish_run(
            event_id,
            status="failed",
            agents=[],
            action="failed",
            confidence=None,
            errors=[f"{type(error).__name__}: {error}"[:500]],
            outputs={},
        )
        return {"event_id": event_id, "status": "failed", "error": type(error).__name__}

    results["run_duration_seconds"] = round(time.monotonic() - started, 3)
    status = outcome(results)
    finish_run(
        event_id,
        status=status,
        agents=list(results.get("completed_agents", [])),
        action=("dry run" if settings.DRY_RUN else "live") + f" / {status}",
        confidence=results.get("confidence"),
        errors=list(results.get("errors", [])),
        outputs={k: results.get(k) for k in OUTPUT_KEYS if results.get(k) is not None},
    )
    logger.info(
        "[%s] %s in %.1fs; agents=%s",
        event_id,
        status,
        results["run_duration_seconds"],
        results.get("completed_agents"),
    )
    return {**{k: v for k, v in results.items() if k != "messages"}, "status": status}
