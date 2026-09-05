"""
The HTTP surface.

``POST /webhook`` accepted any JSON from any caller and answered
``{"status": "accepted"}`` -- for a valid trigger, for an unknown one, for
anything. What a caller could cause with it: model spend, a comment on any
pull request the GitHub token could reach, and a status change on a
PagerDuty incident. There was no way to learn what happened to an event
afterwards; the background task printed and, on failure, returned None.

Now the body must carry a valid ``X-Hub-Signature-256`` (GitHub's HMAC scheme)
or ``X-API-Key``; the trigger is one of a known set; the response is ``202``
with an event id; and ``GET /events/{id}`` returns the audit row.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections import OrderedDict
from contextlib import asynccontextmanager
from typing import Any, Literal

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ValidationError

from agent_graph import TRIGGERS, run_devops_workflow
from config import settings
from database import create_db_and_tables, get_engine, get_run
from security import API_KEY_HEADER, SIGNATURE_HEADER, is_authorised

logger = logging.getLogger("devops_os.api")

MAX_BODY_BYTES = 256 * 1024
REPO_PATTERN = r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$"

TriggerType = Literal[
    "pr_opened", "ci_failed", "scheduled_infra", "pagerduty", "pr_merged", "scheduled_security", "manual"
]
assert set(TriggerType.__args__) == set(TRIGGERS)


class EventPayload(BaseModel):
    trigger_type: TriggerType
    repo: str | None = Field(default=None, pattern=REPO_PATTERN)
    branch: str | None = Field(default=None, max_length=200)
    commit_sha: str | None = Field(default=None, pattern=r"^[0-9a-fA-F]{7,40}$")
    payload: dict[str, Any] = Field(default_factory=dict)


# Recently seen events, for the window between "accepted" and the audit row.
_recent: OrderedDict[str, dict] = OrderedDict()


def _remember(event_id: str, record: dict) -> None:
    _recent[event_id] = record
    while len(_recent) > settings.MAX_EVENTS_IN_MEMORY:
        _recent.popitem(last=False)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.basicConfig(level=settings.LOG_LEVEL, format="%(levelname)-8s %(name)s %(message)s")
    problems = settings.problems()
    if settings.is_production and problems:
        raise RuntimeError("refusing to start: " + "; ".join(problems))
    for problem in problems:
        logger.warning("configuration: %s", problem)
    create_db_and_tables()
    auth = "on" if (settings.has_webhook_secret or settings.has_api_key) else "OFF"
    logger.info("ready: environment=%s dry_run=%s auth=%s", settings.ENVIRONMENT, settings.DRY_RUN, auth)
    yield


app = FastAPI(
    title="DevOps OS API",
    description="Routes CI/CD, review, incident and infrastructure events to specialist agents.",
    version="0.2.0",
    lifespan=lifespan,
    docs_url=None if settings.is_production else "/docs",
    openapi_url=None if settings.is_production else "/openapi.json",
)


@app.get("/health", tags=["ops"])
def health() -> dict[str, Any]:
    return {"status": "ok", "environment": settings.ENVIRONMENT, "dry_run": settings.DRY_RUN, "version": app.version}


@app.get("/ready", tags=["ops"])
def ready() -> JSONResponse:
    checks: dict[str, dict[str, Any]] = {}
    try:
        with get_engine().connect() as conn:
            conn.exec_driver_sql("SELECT 1")
        checks["database"] = {"ok": True, "detail": "reachable"}
    except Exception as error:
        checks["database"] = {"ok": False, "detail": f"unreachable: {type(error).__name__}"}
    authed = settings.has_webhook_secret or settings.has_api_key
    checks["auth"] = {
        "ok": authed or not settings.is_production,
        "detail": "signature or key configured" if authed else "OPEN (development only)",
    }
    anthropic = "set" if settings.ANTHROPIC_API_KEY.strip() else "unset"
    openai = "set" if settings.OPENAI_API_KEY.strip() else "unset"
    checks["providers"] = {
        "ok": anthropic == "set" or openai == "set",
        "detail": f"anthropic={anthropic} openai={openai}",
    }
    checks["writes"] = {
        "ok": True,
        "detail": "dry run: nothing is written externally"
        if settings.DRY_RUN
        else f"LIVE for repos: {sorted(settings.allowed_repos) or 'none'}",
    }
    is_ready = all(c["ok"] for c in checks.values())
    return JSONResponse(status_code=200 if is_ready else 503, content={"ready": is_ready, "checks": checks})


@app.post("/webhook", status_code=status.HTTP_202_ACCEPTED, tags=["events"])
async def receive_event(request: Request, background: BackgroundTasks) -> dict[str, Any]:
    body = await request.body()
    if len(body) > MAX_BODY_BYTES:
        raise HTTPException(status_code=413, detail=f"body exceeds {MAX_BODY_BYTES} bytes")

    if not is_authorised(body, request.headers.get(SIGNATURE_HEADER), request.headers.get(API_KEY_HEADER)):
        raise HTTPException(
            status_code=401,
            detail="missing or invalid signature / API key",
            headers={"WWW-Authenticate": SIGNATURE_HEADER},
        )

    try:
        event = EventPayload.model_validate(json.loads(body or b"{}"))
    except json.JSONDecodeError as error:
        raise HTTPException(status_code=422, detail="body is not JSON") from error
    except ValidationError as error:
        raise HTTPException(status_code=422, detail=json.loads(error.json())) from error

    event_id = uuid.uuid4().hex
    logger.info("[%s] accepted %s for %s", event_id, event.trigger_type, event.repo)
    _remember(
        event_id, {"event_id": event_id, "status": "queued", "trigger_type": event.trigger_type, "repo": event.repo}
    )
    background.add_task(run_devops_workflow, event_id, event.model_dump())
    return {"event_id": event_id, "status": "queued", "trigger_type": event.trigger_type, "dry_run": settings.DRY_RUN}


@app.get("/events/{event_id}", tags=["events"])
def event_status(event_id: str) -> dict[str, Any]:
    row = get_run(event_id)
    if row is not None:
        return row
    if event_id in _recent:
        return _recent[event_id]
    raise HTTPException(status_code=404, detail="unknown event id")
