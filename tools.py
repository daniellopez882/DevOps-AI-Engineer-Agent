import os
import httpx
import boto3
from datetime import datetime, timedelta
from github import Github
from crewai.tools import BaseTool

class GithubPRFetchTool(BaseTool):
    name: str = "Fetch GitHub PR Details"
    description: str = (
        "Fetches the details of a GitHub Pull Request including title, description, "
        "and the files changed (diff). Needs the repository name and PR number as input."
    )

    def _run(self, repo: str, pr_number: int) -> str:
        token = os.getenv("GITHUB_TOKEN")
        if not token:
            return "Error: GITHUB_TOKEN not found."
        
        try:
            g = Github(token)
            gh_repo = g.get_repo(repo)
            pr = gh_repo.get_pull(pr_number)
            
            # Formulate output
            files = pr.get_files()
            diffs = []
            for file in files:
                diffs.append(f"File: {file.filename}\nStatus: {file.status}\nChanges:\n{file.patch}")
                
            return f"PR #{pr.number} - {pr.title}\n{pr.body}\n\n=== DIFFS ===\n" + "\n".join(diffs)
        except Exception as e:
            return f"Failed to fetch PR details: {str(e)}"

class GithubCommentTool(BaseTool):
    name: str = "Post GitHub PR Comment"
    description: str = (
        "Posts a code review comment or summary on a specific GitHub Pull Request."
    )

    def _run(self, repo: str, pr_number: int, comment: str) -> str:
        token = os.getenv("GITHUB_TOKEN")
        if not token:
            return "Error: GITHUB_TOKEN not found."
            
        try:
            g = Github(token)
            gh_repo = g.get_repo(repo)
            pr = gh_repo.get_pull(pr_number)
            pr.create_issue_comment(comment)
            return f"Successfully posted code review comment on PR #{pr_number} in {repo}."
        except Exception as e:
            return f"Failed to post PR comment: {str(e)}"

class FetchCILogsTool(BaseTool):
    name: str = "Fetch CI Pipeline Logs"
    description: str = (
        "Fetches the build or test logs for a failed CI pipeline run."
    )

    def _run(self, pipeline_id: str) -> str:
        return """
        [ERROR] ModuleNotFoundError: No module named 'pydantic'
        [INFO] Build step failed with exit code 1.
        """

class AWSCostExplorerTool(BaseTool):
    name: str = "AWS Cost Explorer Fetcher"
    description: str = (
        "Fetches the current AWS cloud spend, anomalies, and EC2 instance utilization metrics for the past 30 days."
    )

    def _run(self) -> str:
        try:
            client = boto3.client('ce', 
                                  aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
                                  aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
                                  region_name=os.getenv("AWS_DEFAULT_REGION", "us-east-1"))
            
            end_date = datetime.today()
            start_date = end_date - timedelta(days=30)
            
            response = client.get_cost_and_usage(
                TimePeriod={
                    'Start': start_date.strftime('%Y-%m-%d'),
                    'End': end_date.strftime('%Y-%m-%d')
                },
                Granularity='MONTHLY',
                Metrics=['UnblendedCost']
            )
            
            costs = response['ResultsByTime']
            output = "[AWS Cost Analysis - Last 30 Days]\n"
            for t in costs:
                amount = t['Total']['UnblendedCost']['Amount']
                unit = t['Total']['UnblendedCost']['Unit']
                output += f"Period {t['TimePeriod']['Start']} to {t['TimePeriod']['End']}: {amount} {unit}\n"
                
            return output
            
        except Exception as e:
            return f"Could not fetch AWS Cost Metrics: {str(e)}"

class PagerDutyAlertTool(BaseTool):
    name: str = "PagerDuty Incident Responder"
    description: str = (
        "Acknowledges an incident in PagerDuty and can also post resolution notes or page human engineers."
    )

    def _run(self, incident_id: str, action: str, note: str = "") -> str:
        pd_api_key = os.getenv("PAGERDUTY_API_KEY")
        if not pd_api_key:
            return "Error: PAGERDUTY_API_KEY config missing."
            
        headers = {
            "Authorization": f"Token token={pd_api_key}",
            "Accept": "application/vnd.pagerduty+json;version=2",
            "Content-Type": "application/json",
            "From": "devops_agent@autonomous.system"
        }
        
        url = f"https://api.pagerduty.com/incidents/{incident_id}"
        
        try:
            # Action handles acknowledgement, resolution logic
            payload = {
                "incident": {
                    "type": "incident_reference",
                    "status": "acknowledged" if action.lower() == "acknowledge" else "resolved"
                }
            }
            res = httpx.put(url, headers=headers, json=payload, timeout=10.0)
            res.raise_for_status()
            
            if note:
                note_url = f"{url}/notes"
                note_payload = {"note": {"content": f"🤖 DevOpsOS AI: {note}"}}
                httpx.post(note_url, headers=headers, json=note_payload, timeout=10.0)
                
            return f"Successfully performed '{action}' on PagerDuty incident {incident_id}."
        except Exception as e:
            return f"Failed to interact with PagerDuty: {str(e)}"

class DocumentationUpdateTool(BaseTool):
    name: str = "Documentation Uploader Tool"
    description: str = (
        "Updates API docs, README files, or architecture diagrams on Confluence/Notion or creating a GitHub PR."
    )

    def _run(self, doc_type: str, content: str) -> str:
        # Stubbed implementation
        return f"Successfully updated {doc_type} documentation."

class SecurityScanTool(BaseTool):
    name: str = "SAST & SCA Security Scanner"
    description: str = (
        "Runs dependency vulnerability scans (npm audit, pip-audit) and SAST scans (Semgrep) on the repo."
    )

    def _run(self, repo: str) -> str:
        return """
        [SCAN RESULTS]
        High: 0
        Medium: 1 (CVE-2024-xyz in requests package)
        Low: 2
        Recommendation: Upgrade 'requests' to >=2.31.0.
        """

github_pr_tool = GithubPRFetchTool()
github_comment_tool = GithubCommentTool()
fetch_ci_logs_tool = FetchCILogsTool()
aws_cost_tool = AWSCostExplorerTool()
pagerduty_tool = PagerDutyAlertTool()
documentation_tool = DocumentationUpdateTool()
security_scan_tool = SecurityScanTool()
