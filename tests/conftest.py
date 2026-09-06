"""
Shared fixtures. No test reaches a network, a model, GitHub, PagerDuty or AWS.

The environment is set before ``config`` is imported, because ``settings`` is
built at import time.
"""

from __future__ import annotations

import os
import pathlib
import tempfile

import pytest

_TMP = pathlib.Path(tempfile.mkdtemp())
os.environ.setdefault("ENVIRONMENT", "testing")
os.environ.setdefault("DATABASE_URL", f"sqlite:///{(_TMP / 'audit.db').as_posix()}")
os.environ.setdefault("WEBHOOK_SECRET", "test-webhook-secret")
os.environ.setdefault("API_KEY", "test-api-key-not-real")
os.environ.setdefault("ALLOWED_REPOS", "octo/repo, Octo/Other")
os.environ.setdefault("ANTHROPIC_API_KEY", "")
os.environ.setdefault("OPENAI_API_KEY", "")
os.environ.pop("DRY_RUN", None)

from fastapi.testclient import TestClient

import agent_graph
from config import settings
from database import create_db_and_tables
from main import app
from security import sign

AUTH = {"X-API-Key": os.environ["API_KEY"]}


@pytest.fixture(scope="session", autouse=True)
def _tables():
    create_db_and_tables()


class FakeAgent:
    def __init__(self, kind):
        self.kind = kind


class FakeCrew:
    """Stands in for DevOpsOSCrew: hands back a marker instead of a crewai Agent."""

    def create_code_review_agent(self):
        return FakeAgent("code_review")

    def create_ci_monitor_agent(self):
        return FakeAgent("ci_monitor")

    def create_infra_optimizer_agent(self):
        return FakeAgent("infra")

    def create_incident_responder_agent(self):
        return FakeAgent("incident")

    def create_documentation_agent(self):
        return FakeAgent("documentation")

    def create_security_audit_agent(self):
        return FakeAgent("security")


@pytest.fixture
def scripted_crew(monkeypatch):
    """
    Replace the crew with a script: ``scripted_crew('{"confidence": 0.8}')`` makes
    every specialist return that text. Returns the list of (agent kind, task)
    calls made.
    """
    calls: list[tuple[str, object]] = []

    def install(raw="{}", *, raise_error=None):
        def run_crew(agent, task):
            calls.append((agent.kind, task))
            if raise_error is not None:
                raise raise_error
            return raw

        monkeypatch.setattr(agent_graph, "DevOpsOSCrew", FakeCrew)
        monkeypatch.setattr(agent_graph, "run_crew", run_crew)
        # tasks.py builds real crewai Task objects, which validate the agent
        # type; hand the node a plain description instead.
        for name in (
            "get_code_review_task",
            "get_ci_monitor_task",
            "get_infra_optimization_task",
            "get_incident_responder_task",
            "get_documentation_task",
            "get_security_audit_task",
        ):
            monkeypatch.setattr(agent_graph, name, lambda agent, *args, _n=name: (_n, args))
        return calls

    return install


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def signed():
    """Headers carrying a valid GitHub-style signature for ``body``."""

    def make(body: bytes) -> dict:
        return {"X-Hub-Signature-256": sign(body, settings.WEBHOOK_SECRET), "Content-Type": "application/json"}

    return make
