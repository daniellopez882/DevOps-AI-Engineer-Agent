"""
The specialist agents.

``__init__`` used to build six model clients -- three Anthropic, three OpenAI
-- before any node asked for one, so every node needed both providers' keys.
Each factory now builds the one model its agent uses, when it is called.
"""

from __future__ import annotations

from typing import Any

from devops_agent_prompts import (
    CI_MONITOR_PROMPT,
    CODE_REVIEW_PROMPT,
    DOCUMENTATION_PROMPT,
    INCIDENT_RESPONDER_PROMPT,
    INFRA_OPTIMIZER_PROMPT,
    SECURITY_AUDIT_PROMPT,
    build_agent_prompt,
)
from llm import for_provider
from tools import (
    aws_cost_tool,
    documentation_tool,
    fetch_ci_logs_tool,
    github_comment_tool,
    github_pr_tool,
    pagerduty_tool,
    security_scan_tool,
)

# Which provider each specialist uses. Configuration decides the model names.
PROVIDER = {
    "code_review": "anthropic",
    "ci_monitor": "openai",
    "infra": "openai",
    "incident": "anthropic",
    "documentation": "anthropic",
    "security": "anthropic",
}


class DevOpsOSCrew:
    def _agent(self, kind: str, role: str, goal: str, prompt: str, tools: list) -> Any:
        from crewai import Agent

        return Agent(
            role=role,
            goal=goal,
            backstory=build_agent_prompt(prompt),
            llm=for_provider(PROVIDER[kind]),
            tools=tools,
            verbose=False,
            allow_delegation=False,
        )

    def create_code_review_agent(self) -> Any:
        return self._agent(
            "code_review",
            "Senior software and security reviewer",
            "Review a pull request's diff for correctness, security and maintainability, and post one review comment.",
            CODE_REVIEW_PROMPT,
            [github_pr_tool, github_comment_tool],
        )

    def create_ci_monitor_agent(self) -> Any:
        return self._agent(
            "ci_monitor",
            "CI pipeline analyst",
            "Diagnose a failed pipeline from its logs and propose a fix.",
            CI_MONITOR_PROMPT,
            [fetch_ci_logs_tool],
        )

    def create_infra_optimizer_agent(self) -> Any:
        return self._agent(
            "infra",
            "Cloud cost analyst",
            "Report on cloud spend and propose savings, with the risk of each.",
            INFRA_OPTIMIZER_PROMPT,
            [aws_cost_tool],
        )

    def create_incident_responder_agent(self) -> Any:
        return self._agent(
            "incident",
            "Incident responder",
            "Acknowledge the incident, record findings as notes, and only resolve when the cause is confirmed.",
            INCIDENT_RESPONDER_PROMPT,
            [pagerduty_tool],
        )

    def create_documentation_agent(self) -> Any:
        return self._agent(
            "documentation",
            "Technical writer",
            "Identify documentation affected by a merge and draft the updates.",
            DOCUMENTATION_PROMPT,
            [documentation_tool, github_pr_tool],
        )

    def create_security_audit_agent(self) -> Any:
        return self._agent(
            "security",
            "Security auditor",
            "Report the security posture of a repository from the scanners available.",
            SECURITY_AUDIT_PROMPT,
            [security_scan_tool],
        )
