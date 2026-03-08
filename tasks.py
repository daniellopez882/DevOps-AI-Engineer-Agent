from crewai import Task

def get_code_review_task(agent, repo: str, pr_number: int) -> Task:
    return Task(
        description=f"""
        1. Fetch pull request details and diffs for {repo} PR #{pr_number}.
        2. Perform static analysis, code quality, and security scans on the diffs.
        3. Formulate a final review output and decision (APPROVE | REQUEST_CHANGES | COMMENT).
        4. Post the review as a comment to GitHub.
        Ensure you adhere to your rigorous FAANG-level expertise!
        """,
        expected_output="A JSON-formatted string matching the OUTPUT FORMAT specified in your system prompt.",
        agent=agent
    )

def get_ci_monitor_task(agent, repo: str, run_id: str) -> Task:
    return Task(
        description=f"""
        1. Parse the failed CI pipeline logs for {repo} run {run_id}.
        2. Determine the failure root cause (Build, Infrastructure, Environment).
        3. Generate an auto-fix diff if confidence > 0.90, else generate Slack alert payload.
        """,
        expected_output="A JSON-formatted string summarizing the failure and proposed fix, matching OUTPUT FORMAT.",
        agent=agent
    )

def get_infra_optimization_task(agent) -> Task:
    return Task(
        description="""
        1. Scan current AWS infrastructure for wasted compute and database resources.
        2. Filter underutilized resources, verify against risk levels.
        3. Outline Terraform drift and generate recommendations.
        """,
        expected_output="A complete JSON-formatted financial and infra optimization report.",
        agent=agent
    )

def get_incident_responder_task(agent, incident_id: str) -> Task:
    return Task(
        description=f"""
        1. Acknowledge PagerDuty incident {incident_id} immediately.
        2. Hypothesize the correct root cause.
        3. Attempt mitigation, or escalate via note if unrecoverable safely.
        """,
        expected_output="A JSON-formatted incident report covering start_time, mitigation notes, and next steps.",
        agent=agent
    )

def get_documentation_task(agent, repo: str) -> Task:
    return Task(
        description=f"""
        1. Analyze recent PR merges and identify missing or outdated documentation in {repo}.
        2. Generate missing docstrings, update API endpoints, and update READMEs.
        3. Upload or push these changes to a repository or Confluence.
        """,
        expected_output="A JSON-formatted string matching the OUTPUT FORMAT specified in your system prompt.",
        agent=agent
    )

def get_security_audit_task(agent, repo: str) -> Task:
    return Task(
        description=f"""
        1. Perform a complete dependency vulnerability scan and SAST against {repo}.
        2. Detect any secrets committed to the repository.
        3. Outline dynamic scan findings mapping to OWASP top 10.
        """,
        expected_output="A complete JSON-formatted security posture report and action steps.",
        agent=agent
    )
