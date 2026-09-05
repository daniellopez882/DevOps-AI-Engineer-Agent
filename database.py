"""
The audit trail.

Three things the previous version did:

* ``confidence=0.99`` was written for every run, unconditionally -- including
  a run whose trigger routed nowhere and whose ``completed_agents`` was empty.
  An audit log that records a made-up confidence is worse than one that
  records none.
* The engine was created at import time from ``os.getenv``, so importing the
  module for any reason connected to whatever ``DATABASE_URL`` said.
* ``datetime.utcnow`` -- naive, and deprecated.

Now: one row per run, written when it starts and updated when it ends, with
the outcome (``completed`` / ``failed`` / ``no_route`` / ``needs_human``),
any errors, and the confidence the model reported -- or nothing.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any

from sqlmodel import Field, Session, SQLModel, create_engine, select

from config import settings

logger = logging.getLogger("devops_os.db")

REDACTED_KEYS = frozenset({"token", "secret", "password", "authorization", "api_key", "apikey", "key"})

STATUSES = ("running", "completed", "failed", "no_route", "needs_human")


def _now() -> datetime:
    return datetime.now(UTC)


class AuditLog(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    event_id: str = Field(index=True)
    trigger_type: str
    repo: str | None = None
    agent_invoked: str = ""
    status: str = "running"
    action_taken: str = ""
    confidence: float | None = None  # what the model reported, or nothing
    dry_run: bool = True
    errors: str = "[]"
    started_at: datetime = Field(default_factory=_now)
    finished_at: datetime | None = None
    payload_dump: str = "{}"


def redact(value: Any) -> Any:
    """Drop values under secret-looking keys before they reach the log."""
    if isinstance(value, dict):
        return {
            k: ("[redacted]" if any(marker in str(k).lower() for marker in REDACTED_KEYS) else redact(v))
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [redact(v) for v in value]
    return value


@lru_cache(maxsize=1)
def get_engine():
    return create_engine(settings.DATABASE_URL, echo=False)


def create_db_and_tables() -> None:
    SQLModel.metadata.create_all(get_engine())


def start_run(event_id: str, trigger_type: str, repo: str | None, payload: dict) -> None:
    row = AuditLog(
        event_id=event_id,
        trigger_type=trigger_type,
        repo=repo,
        dry_run=settings.DRY_RUN,
        payload_dump=json.dumps(redact({"input_payload": payload}), default=str),
    )
    with Session(get_engine()) as session:
        session.add(row)
        session.commit()


def finish_run(
    event_id: str,
    *,
    status: str,
    agents: list[str],
    action: str,
    confidence: float | None,
    errors: list[str],
    outputs: dict,
) -> None:
    if status not in STATUSES:
        raise ValueError(f"unknown status {status!r}")
    with Session(get_engine()) as session:
        row = session.exec(select(AuditLog).where(AuditLog.event_id == event_id)).first()
        if row is None:
            row = AuditLog(event_id=event_id, trigger_type="unknown")
        row.status = status
        row.agent_invoked = ", ".join(agents)
        row.action_taken = action
        row.confidence = confidence
        row.errors = json.dumps(errors)
        row.finished_at = _now()
        existing = json.loads(row.payload_dump or "{}")
        existing["output"] = redact(outputs)
        row.payload_dump = json.dumps(existing, default=str)
        session.add(row)
        session.commit()


def get_run(event_id: str) -> dict | None:
    with Session(get_engine()) as session:
        row = session.exec(select(AuditLog).where(AuditLog.event_id == event_id)).first()
        if row is None:
            return None
        return {
            "event_id": row.event_id,
            "trigger_type": row.trigger_type,
            "repo": row.repo,
            "status": row.status,
            "agents": [a for a in row.agent_invoked.split(", ") if a],
            "action": row.action_taken,
            "confidence": row.confidence,
            "dry_run": row.dry_run,
            "errors": json.loads(row.errors or "[]"),
            "started_at": row.started_at.isoformat(),
            "finished_at": row.finished_at.isoformat() if row.finished_at else None,
        }
