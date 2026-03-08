from crewai import Agent
from llm_config import get_gpt4o_model, get_claude_model
from devops_agent_prompts import (
    CODE_REVIEW_PROMPT, 
    CI_MONITOR_PROMPT, 
    INFRA_OPTIMIZER_PROMPT,
    INCIDENT_RESPONDER_PROMPT,
    DOCUMENTATION_PROMPT,
    SECURITY_AUDIT_PROMPT,
    build_agent_prompt
)
from tools import (
    github_pr_tool,
    github_comment_tool,
    fetch_ci_logs_tool,
    aws_cost_tool,
    pagerduty_tool,
    documentation_tool,
    security_scan_tool
)

class DevOpsOSCrew:
    """
    CrewAI setups for deeper multi-step task resolution.
    Agents use specific tools tailored to their environment.
    """
    
    def __init__(self):
        self.code_reviewer_llm = get_claude_model()
        self.ci_monitor_llm = get_gpt4o_model()
        self.infra_llm = get_gpt4o_model()
        self.incident_llm = get_claude_model()
        self.doc_llm = get_claude_model()
        self.security_llm = get_claude_model()

    def create_code_review_agent(self) -> Agent:
        return Agent(
            role='Senior Staff Software & Security Engineer',
            goal='Execute meticulous PR analysis, security scan, and verify SOLID principles.',
            backstory=build_agent_prompt(CODE_REVIEW_PROMPT),
            verbose=True,
            allow_delegation=False,
            llm=self.code_reviewer_llm,
            tools=[github_pr_tool, github_comment_tool]
        )
        
    def create_ci_monitor_agent(self) -> Agent:
        return Agent(
            role='CI/CD Pipeline Intelligence Engineer',
            goal='Diagnose pipeline failures precisely and issue rapid auto-fixes.',
            backstory=build_agent_prompt(CI_MONITOR_PROMPT),
            verbose=True,
            allow_delegation=False,
            llm=self.ci_monitor_llm,
            tools=[fetch_ci_logs_tool]
        )

    def create_infra_optimizer_agent(self) -> Agent:
        return Agent(
            role='Cloud Cost & Infrastructure Optimizer',
            goal='Analyze multi-cloud environments for waste detection and propose Terraform IAC changes.',
            backstory=build_agent_prompt(INFRA_OPTIMIZER_PROMPT),
            verbose=True,
            allow_delegation=False,
            llm=self.infra_llm,
            tools=[aws_cost_tool]
        )

    def create_incident_responder_agent(self) -> Agent:
        return Agent(
            role='Site Reliability Engine',
            goal='Act within seconds on P1 incidents, acknowledge alerts, and resolve autonomously or escalate.',
            backstory=build_agent_prompt(INCIDENT_RESPONDER_PROMPT),
            verbose=True,
            allow_delegation=False,
            llm=self.incident_llm,
            tools=[pagerduty_tool]
        )

    def create_documentation_agent(self) -> Agent:
        return Agent(
            role='Technical Documentation Engineer',
            goal='Ensure API docs, README files, and architectures are correctly documented after PR merges.',
            backstory=build_agent_prompt(DOCUMENTATION_PROMPT),
            verbose=True,
            allow_delegation=False,
            llm=self.doc_llm,
            tools=[documentation_tool, github_pr_tool]
        )

    def create_security_audit_agent(self) -> Agent:
        return Agent(
            role='Information Security Intelligence Engine',
            goal='Continuously scan implementations for CVEs and vulnerabilities on scheduled intervals or merges.',
            backstory=build_agent_prompt(SECURITY_AUDIT_PROMPT),
            verbose=True,
            allow_delegation=False,
            llm=self.security_llm,
            tools=[security_scan_tool]
        )
