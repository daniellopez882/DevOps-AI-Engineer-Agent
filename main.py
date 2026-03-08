from fastapi import FastAPI, BackgroundTasks, HTTPException
from pydantic import BaseModel
import uvicorn
import uuid
import time
from typing import Dict, Any, Optional
from agent_graph import run_devops_workflow

from contextlib import asynccontextmanager
from database import create_db_and_tables

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize Database Tables
    create_db_and_tables()
    yield

app = FastAPI(
    title="DevOps OS - AI Engineer API",
    description="API for the autonomous DevOps AI orchestrator. 50-year engineering expertise within an agentic system.",
    version="1.0.0",
    lifespan=lifespan
)

class EventPayload(BaseModel):
    trigger_type: str # pr_opened, ci_failed, scheduled_infra, pagerduty, manual
    repo: Optional[str] = None
    branch: Optional[str] = None
    commit_sha: Optional[str] = None
    payload: Optional[Dict[str, Any]] = None

@app.get("/")
def read_root():
    return {"status": "operational", "service": "DevOps OS AI Engineer"}

@app.post("/webhook")
def receive_event(event: EventPayload, background_tasks: BackgroundTasks):
    """
    Unified webhook endpoint to receive events from GitHub, Jenkins, PagerDuty, etc.
    It kicks off the LangGraph orchestration in the background to handle the task.
    """
    event_id = str(uuid.uuid4())
    print(f"[{event_id}] Received {event.trigger_type} event for {event.repo}")
    
    background_tasks.add_task(run_devops_workflow, event_id, event.dict())
    
    return {
        "status": "accepted",
        "event_id": event_id,
        "trigger": event.trigger_type,
        "message": "Event queued for DevOpsOS orchestrator."
    }

if __name__ == "__main__":
    print("🚀 Starting DevOps OS API Services...")
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
