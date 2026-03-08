import os
import json
from datetime import datetime
from typing import Optional
from sqlmodel import Field, SQLModel, create_engine, Session

class AuditLog(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    event_id: str = Field(index=True)
    trigger_type: str
    repo: Optional[str] = None
    agent_invoked: str
    action_taken: str
    confidence: float
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    payload_dump: str = Field(default="{}") # Store structured output as text

# Database setup
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./devops_os.db")
# Using sqlite fallback if postgres not configured for local dev
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL, echo=False)

def create_db_and_tables():
    SQLModel.metadata.create_all(engine)

def log_audit_trail(event_id: str, trigger_type: str, repo: str, agent_invoked: str, action: str, confidence: float, payload: dict):
    new_log = AuditLog(
        event_id=event_id,
        trigger_type=trigger_type,
        repo=repo,
        agent_invoked=agent_invoked,
        action_taken=action,
        confidence=confidence,
        payload_dump=json.dumps(payload)
    )
    with Session(engine) as session:
        session.add(new_log)
        session.commit()
