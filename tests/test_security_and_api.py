"""
Who may start a workflow, and what the API does with an event.

Reproduced on the original: ``POST /webhook`` with no credentials and
``trigger_type: "nonsense"`` answered ``200 {"status": "accepted"}``.
"""

from __future__ import annotations

import json

import pytest

from config import settings
from security import api_key_is_valid, is_authorised, sign, signature_is_valid
from tests.conftest import AUTH

VALID = {"trigger_type": "pr_opened", "repo": "octo/repo", "payload": {"pr_number": 7}}


class TestSignatures:
    def test_a_signature_round_trips(self):
        body = b'{"a": 1}'
        assert signature_is_valid(body, sign(body, "s"), "s")

    def test_a_tampered_body_fails(self):
        assert not signature_is_valid(b'{"a": 2}', sign(b'{"a": 1}', "s"), "s")

    def test_a_wrong_secret_fails(self):
        body = b"x"
        assert not signature_is_valid(body, sign(body, "right"), "wrong")

    @pytest.mark.parametrize("header", [None, "", "sha256=", "garbage"])
    def test_missing_or_malformed_headers_fail(self, header):
        assert not signature_is_valid(b"x", header, "s")

    def test_the_header_has_githubs_shape(self):
        assert sign(b"x", "s").startswith("sha256=")

    def test_api_keys_compare_in_constant_time_and_exactly(self):
        assert api_key_is_valid("k", "k")
        assert not api_key_is_valid("k ", "kk")
        assert not api_key_is_valid(None, "k")

    def test_with_nothing_configured_requests_are_allowed(self, monkeypatch):
        monkeypatch.setattr(settings, "WEBHOOK_SECRET", "")
        monkeypatch.setattr(settings, "API_KEY", "")
        assert is_authorised(b"x", None, None)

    def test_with_a_secret_configured_an_unsigned_request_is_refused(self):
        assert not is_authorised(b"x", None, None)


class TestWebhookAuth:
    def test_no_credentials_is_401(self, client):
        response = client.post("/webhook", json=VALID)
        assert response.status_code == 401
        assert response.headers["WWW-Authenticate"] == "X-Hub-Signature-256"

    def test_a_bad_signature_is_401(self, client):
        response = client.post("/webhook", json=VALID, headers={"X-Hub-Signature-256": "sha256=deadbeef"})
        assert response.status_code == 401

    def test_a_bad_api_key_is_401(self, client):
        assert client.post("/webhook", json=VALID, headers={"X-API-Key": "nope"}).status_code == 401

    def test_a_valid_signature_is_accepted(self, client, signed, scripted_crew):
        scripted_crew('{"decision": "APPROVE", "confidence": 0.9}')
        body = json.dumps(VALID).encode()
        response = client.post("/webhook", content=body, headers=signed(body))
        assert response.status_code == 202, response.text
        assert response.json()["status"] == "queued"
        assert response.json()["dry_run"] is True

    def test_a_valid_api_key_is_accepted(self, client, scripted_crew):
        scripted_crew("{}")
        assert client.post("/webhook", json=VALID, headers=AUTH).status_code == 202


class TestWebhookValidation:
    @pytest.mark.parametrize("trigger", ["nonsense", "", "PR_OPENED", "deploy"])
    def test_an_unknown_trigger_is_422_not_accepted(self, client, trigger):
        response = client.post("/webhook", json={**VALID, "trigger_type": trigger}, headers=AUTH)
        assert response.status_code == 422, response.text

    @pytest.mark.parametrize("repo", ["not-a-repo", "a/b/c", "owner/", "/name"])
    def test_a_malformed_repo_is_422(self, client, repo):
        assert client.post("/webhook", json={**VALID, "repo": repo}, headers=AUTH).status_code == 422

    def test_non_json_is_422(self, client):
        response = client.post("/webhook", content=b"not json", headers={**AUTH, "Content-Type": "application/json"})
        assert response.status_code == 422

    def test_an_oversized_body_is_413(self, client):
        body = json.dumps({**VALID, "payload": {"blob": "x" * 300_000}}).encode()
        response = client.post("/webhook", content=body, headers={**AUTH, "Content-Type": "application/json"})
        assert response.status_code == 413


class TestEvents:
    def test_an_accepted_event_can_be_looked_up_with_its_outcome(self, client, scripted_crew):
        scripted_crew('{"decision": "COMMENT", "confidence": 0.75}')
        event_id = client.post("/webhook", json=VALID, headers=AUTH).json()["event_id"]
        record = client.get(f"/events/{event_id}").json()
        assert record["status"] == "completed"
        assert record["agents"] == ["CodeReviewAgent"]
        assert record["confidence"] == 0.75
        assert record["dry_run"] is True

    def test_an_event_that_needs_a_human_says_so(self, client, scripted_crew):
        calls = scripted_crew("{}")
        event_id = client.post(
            "/webhook", json={"trigger_type": "pr_opened", "repo": "octo/repo"}, headers=AUTH
        ).json()["event_id"]
        record = client.get(f"/events/{event_id}").json()
        assert record["status"] == "needs_human"
        assert "pr_number" in record["errors"][0]
        assert calls == [], "a specialist ran without a pull-request number"

    def test_a_failed_run_is_recorded_as_failed(self, client, scripted_crew):
        scripted_crew(raise_error=RuntimeError("provider down"))
        event_id = client.post("/webhook", json=VALID, headers=AUTH).json()["event_id"]
        record = client.get(f"/events/{event_id}").json()
        assert record["status"] == "failed"
        assert "RuntimeError" in record["errors"][0]

    def test_an_unknown_event_is_404(self, client):
        assert client.get("/events/nope").status_code == 404


class TestOps:
    def test_health(self, client):
        body = client.get("/health").json()
        assert body["status"] == "ok"
        assert body["dry_run"] is True

    def test_ready_reports_each_check(self, client):
        body = client.get("/ready").json()
        assert set(body["checks"]) == {"database", "auth", "providers", "writes"}
        assert body["checks"]["database"]["ok"] is True

    def test_ready_is_honest_about_missing_providers(self, client):
        assert client.get("/ready").json()["checks"]["providers"]["ok"] is False

    def test_production_without_secrets_does_not_start(self, monkeypatch):
        from fastapi.testclient import TestClient

        from main import app

        monkeypatch.setattr(settings, "ENVIRONMENT", "production")
        monkeypatch.setattr(settings, "WEBHOOK_SECRET", "")
        monkeypatch.setattr(settings, "API_KEY", "")
        with pytest.raises(RuntimeError, match="WEBHOOK_SECRET"), TestClient(app):
            pass
