import os
from typing import TypedDict, List, Optional, Annotated
from langgraph.graph.message import add_messages
from langgraph.graph import StateGraph, END
import json
from crewai import Crew

# Import the prompts
from devops_agent_prompts import (
    ORCHESTRATOR_PROMPT,
    CODE_REVIEW_PROMPT,
    CI_MONITOR_PROMPT,
    INFRA_OPTIMIZER_PROMPT,
    INCIDENT_RESPONDER_PROMPT,
    DOCUMENTATION_PROMPT,
    SECURITY_AUDIT_PROMPT,
    build_agent_prompt
)
from crew_agents import DevOpsOSCrew
from tasks import (
    get_code_review_task,
    get_ci_monitor_task,
    get_infra_optimization_task,
    get_incident_responder_task,
    get_documentation_task,
    get_security_audit_task
)
from langchain_core.messages import SystemMessage, HumanMessage

class DevOpsAgentState(TypedDict):
    # Core
    messages: Annotated[list, add_messages]
    event_id: str
    trigger_type: str  # pr_opened | ci_failed | scheduled | pagerduty | manual

    # Payload
    payload: Optional[dict]

    # Project context
    project_profile: Optional[dict]
    repo: Optional[str]
    branch: Optional[str]
    commit_sha: Optional[str]

    # Agent outputs
    code_review: Optional[dict]
    ci_diagnosis: Optional[dict]
    infra_report: Optional[dict]
    incident_report: Optional[dict]
    docs_update: Optional[dict]
    security_report: Optional[dict]

    # Control flow
    priority: str   # P1 | P2 | P3 | P4
    current_agent: Optional[str]
    requires_human: bool
    human_approval_reason: Optional[str]
    action_taken: Optional[str]
    confidence: float

    # Notifications
    slack_posted: bool
    github_comment_posted: bool
    pagerduty_acked: bool

    # Meta
    errors: List[str]
    completed_agents: List[str]
    timestamp: str
    run_duration_seconds: int

def get_base_state(event_id: str, trigger_type: str) -> DevOpsAgentState:
    return {
        "messages": [],
        "event_id": event_id,
        "trigger_type": trigger_type,
        "payload": {},
        "project_profile": None,
        "repo": None,
        "branch": None,
        "commit_sha": None,
        "code_review": None,
        "ci_diagnosis": None,
        "infra_report": None,
        "incident_report": None,
        "docs_update": None,
        "security_report": None,
        "priority": "P3",
        "current_agent": None,
        "requires_human": False,
        "human_approval_reason": None,
        "action_taken": None,
        "confidence": 0.0,
        "slack_posted": False,
        "github_comment_posted": False,
        "pagerduty_acked": False,
        "errors": [],
        "completed_agents": [],
        "timestamp": "",
        "run_duration_seconds": 0
    }

def orchestrator_node(state: DevOpsAgentState):
    """
    The main supervisor/orchestrator.
    Evaluates the event and decides which specialist agent to invoke.
    """
    trigger_type = state.get("trigger_type", "manual")
    priority = "P3"
    
    # Fast conditional edge routing
    next_node = END
    if trigger_type == "pr_opened":
        next_node = "code_review_agent"
    elif trigger_type == "ci_failed":
        next_node = "ci_monitor_agent"
    elif trigger_type == "scheduled_infra":
        next_node = "infra_optimizer_agent"
    elif trigger_type == "pagerduty":
        priority = "P1"
        next_node = "incident_responder_agent"
    elif trigger_type == "pr_merged":
        next_node = "documentation_agent"
    elif trigger_type == "scheduled_security":
        next_node = "security_audit_agent"

    current_messages = state.get("messages", [])
    current_messages.append({"role": "assistant", "content": f"Orchestrator routed {trigger_type} to {next_node}"})

    return {
        "priority": priority,
        "current_agent": next_node,
        "messages": current_messages
    }

def safe_json_parse(raw: str) -> dict:
    # Try to safely extract output from Markdown JSON if exists
    try:
        raw = raw.replace('```json', '').replace('```', '').strip()
        return json.loads(raw)
    except Exception:
        return {"raw_output": raw}

def code_review_agent_node(state: DevOpsAgentState):
    print(f"[{state['event_id']}] CodeReviewAgent (CrewAI) running...")
    crew_factory = DevOpsOSCrew()
    agent = crew_factory.create_code_review_agent()
    
    payload = state.get("payload", {})
    repo = state.get("repo", payload.get("repo", "unknown/repo"))
    pr_number = payload.get("pr_number", 1)

    task = get_code_review_task(agent, repo, pr_number)
    crew = Crew(agents=[agent], tasks=[task], verbose=True)
    
    # Fire agent
    result = crew.kickoff()
    return {
        "code_review": safe_json_parse(result.raw),
        "completed_agents": state.get("completed_agents", []) + ["CodeReviewAgent"]
    }

def ci_monitor_agent_node(state: DevOpsAgentState):
    print(f"[{state['event_id']}] CIMonitorAgent (CrewAI) running...")
    crew_factory = DevOpsOSCrew()
    agent = crew_factory.create_ci_monitor_agent()
    
    payload = state.get("payload", {})
    repo = state.get("repo", payload.get("repo", "unknown/repo"))
    run_id = payload.get("run_id", "run-000")

    task = get_ci_monitor_task(agent, repo, run_id)
    crew = Crew(agents=[agent], tasks=[task], verbose=True)
    
    result = crew.kickoff()
    return {
        "ci_diagnosis": safe_json_parse(result.raw),
        "completed_agents": state.get("completed_agents", []) + ["CIMonitorAgent"]
    }

def infra_optimizer_agent_node(state: DevOpsAgentState):
    print(f"[{state['event_id']}] InfraOptimizerAgent (CrewAI) running...")
    crew_factory = DevOpsOSCrew()
    agent = crew_factory.create_infra_optimizer_agent()
    
    task = get_infra_optimization_task(agent)
    crew = Crew(agents=[agent], tasks=[task], verbose=True)
    
    result = crew.kickoff()
    return {
        "infra_report": safe_json_parse(result.raw),
        "completed_agents": state.get("completed_agents", []) + ["InfraOptimizerAgent"]
    }

def incident_responder_agent_node(state: DevOpsAgentState):
    print(f"[{state['event_id']}] IncidentResponder (CrewAI) running...")
    crew_factory = DevOpsOSCrew()
    agent = crew_factory.create_incident_responder_agent()
    
    payload = state.get("payload", {})
    incident_id = payload.get("incident_id", "INC0001")

    task = get_incident_responder_task(agent, incident_id)
    crew = Crew(agents=[agent], tasks=[task], verbose=True)
    
    result = crew.kickoff()
    return {
        "incident_report": safe_json_parse(result.raw),
        "completed_agents": state.get("completed_agents", []) + ["IncidentResponder"]
    }

def documentation_agent_node(state: DevOpsAgentState):
    print(f"[{state['event_id']}] DocumentationAgent (CrewAI) running...")
    crew_factory = DevOpsOSCrew()
    agent = crew_factory.create_documentation_agent()
    
    payload = state.get("payload", {})
    repo = state.get("repo", payload.get("repo", "unknown/repo"))

    task = get_documentation_task(agent, repo)
    crew = Crew(agents=[agent], tasks=[task], verbose=True)
    
    result = crew.kickoff()
    return {
        "docs_update": safe_json_parse(result.raw),
        "completed_agents": state.get("completed_agents", []) + ["DocumentationAgent"]
    }

def security_audit_agent_node(state: DevOpsAgentState):
    print(f"[{state['event_id']}] SecurityAuditAgent (CrewAI) running...")
    crew_factory = DevOpsOSCrew()
    agent = crew_factory.create_security_audit_agent()
    
    payload = state.get("payload", {})
    repo = state.get("repo", payload.get("repo", "unknown/repo"))

    task = get_security_audit_task(agent, repo)
    crew = Crew(agents=[agent], tasks=[task], verbose=True)
    
    result = crew.kickoff()
    return {
        "security_report": safe_json_parse(result.raw),
        "completed_agents": state.get("completed_agents", []) + ["SecurityAuditAgent"]
    }

# Build the Graph
workflow = StateGraph(DevOpsAgentState)

# Add Nodes
workflow.add_node("orchestrator", orchestrator_node)
workflow.add_node("code_review_agent", code_review_agent_node)
workflow.add_node("ci_monitor_agent", ci_monitor_agent_node)
workflow.add_node("infra_optimizer_agent", infra_optimizer_agent_node)
workflow.add_node("incident_responder_agent", incident_responder_agent_node)
workflow.add_node("documentation_agent", documentation_agent_node)
workflow.add_node("security_audit_agent", security_audit_agent_node)

# set bindings
workflow.set_entry_point("orchestrator")
workflow.add_conditional_edges(
    "orchestrator",
    lambda state: state["current_agent"],
    {
        "code_review_agent": "code_review_agent",
        "ci_monitor_agent": "ci_monitor_agent",
        "infra_optimizer_agent": "infra_optimizer_agent",
        "incident_responder_agent": "incident_responder_agent",
        "documentation_agent": "documentation_agent",
        "security_audit_agent": "security_audit_agent",
        END: END
    }
)

workflow.add_edge("code_review_agent", END)
workflow.add_edge("ci_monitor_agent", END)
workflow.add_edge("infra_optimizer_agent", END)
workflow.add_edge("incident_responder_agent", END)
workflow.add_edge("documentation_agent", END)
workflow.add_edge("security_audit_agent", END)

# Compile
devops_workflow = workflow.compile()

def run_devops_workflow(event_id: str, payload_data: dict):
    from dotenv import load_dotenv
    from database import log_audit_trail
    load_dotenv()
    
    initial_state = get_base_state(event_id, payload_data.get("trigger_type", "manual"))
    initial_state["repo"] = payload_data.get("repo")
    initial_state["payload"] = payload_data.get("payload", {})
    
    print(f"[{event_id}] Starting LangGraph + CrewAI execution...")
    try:
        results = devops_workflow.invoke(initial_state)
        print(f"[{event_id}] Execution completed. Handled by: {results['completed_agents']}")
        
        # Log to Database Audit Trail
        agents = ", ".join(results.get('completed_agents', []))
        trigger = results.get('trigger_type', 'manual')
        repo = results.get('repo', 'unknown')
        payload_dump = {"input_payload": payload_data, "output": {k: v for k, v in results.items() if k in ['code_review', 'ci_diagnosis', 'infra_report', 'incident_report', 'docs_update', 'security_report'] and v is not None}}
        
        log_audit_trail(
            event_id=event_id,
            trigger_type=trigger,
            repo=repo,
            agent_invoked=agents,
            action="Completed Execution",
            confidence=0.99,
            payload=payload_dump
        )
        
        return results
    except Exception as e:
        print(f"[{event_id}] Error in graph execution: {str(e)}")
        return None
