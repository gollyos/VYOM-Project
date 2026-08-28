from __future__ import annotations

from typing import Any
import httpx
from app.connectors.base import (
    BaseConnector,
    ConnectorAuthType,
    ConnectorCategory,
    ConnectorDefinition,
    ConnectorStatus,
    RiskLevel,
    ToolDefinition,
)


class GitHubConnector(BaseConnector):
    """GitHub integration connector for repositories, issues, PRs, and CI."""

    def __init__(self, token: str | None = None):
        defn = ConnectorDefinition(
            id="github",
            name="GitHub",
            slug="github",
            description="Manage repositories, track and create issues, inspect pull requests, and monitor GitHub Actions CI workflows.",
            icon="github",
            category=ConnectorCategory.DEV_TOOLS,
            auth_type=ConnectorAuthType.API_KEY,
            capabilities=["repositories", "issues", "pull_requests", "actions", "comments"],
            permissions=["repo:read", "repo:write", "issues:write", "workflow:read"],
            tools=[
                ToolDefinition(
                    id="github.list_repositories",
                    connector_id="github",
                    name="list_repositories",
                    display_name="List Repositories",
                    description="List public or authenticated user/org repositories on GitHub.",
                    category="dev_tools",
                    input_schema={
                        "type": "object",
                        "properties": {
                            "username": {"type": "string", "description": "Optional user or organization name"},
                            "limit": {"type": "integer", "default": 10, "description": "Maximum number of repos to return"},
                        },
                    },
                    risk_level=RiskLevel.LOW,
                    requires_approval=False,
                ),
                ToolDefinition(
                    id="github.search_issues",
                    connector_id="github",
                    name="search_issues",
                    display_name="Search Issues",
                    description="Search for GitHub issues and pull requests matching a query.",
                    category="dev_tools",
                    input_schema={
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "Search query string, e.g. 'repo:owner/repo is:open is:issue'"},
                            "limit": {"type": "integer", "default": 10},
                        },
                        "required": ["query"],
                    },
                    risk_level=RiskLevel.LOW,
                    requires_approval=False,
                ),
                ToolDefinition(
                    id="github.get_issue",
                    connector_id="github",
                    name="get_issue",
                    display_name="Get Issue Details",
                    description="Fetch detailed information about a specific GitHub issue or pull request.",
                    category="dev_tools",
                    input_schema={
                        "type": "object",
                        "properties": {
                            "repo": {"type": "string", "description": "Full repository name 'owner/repo'"},
                            "issue_number": {"type": "integer", "description": "Issue or PR number"},
                        },
                        "required": ["repo", "issue_number"],
                    },
                    risk_level=RiskLevel.LOW,
                    requires_approval=False,
                ),
                ToolDefinition(
                    id="github.create_issue",
                    connector_id="github",
                    name="create_issue",
                    display_name="Create Issue",
                    description="Create a new issue on a GitHub repository.",
                    category="dev_tools",
                    input_schema={
                        "type": "object",
                        "properties": {
                            "repo": {"type": "string", "description": "Repository in format 'owner/repo'"},
                            "title": {"type": "string", "description": "Issue title"},
                            "body": {"type": "string", "description": "Issue description content in Markdown"},
                            "labels": {"type": "array", "items": {"type": "string"}, "description": "Labels to apply"},
                        },
                        "required": ["repo", "title"],
                    },
                    risk_level=RiskLevel.MEDIUM,
                    requires_approval=False,
                ),
                ToolDefinition(
                    id="github.comment_on_issue",
                    connector_id="github",
                    name="comment_on_issue",
                    display_name="Comment on Issue",
                    description="Post a comment on an existing GitHub issue or pull request.",
                    category="dev_tools",
                    input_schema={
                        "type": "object",
                        "properties": {
                            "repo": {"type": "string", "description": "Repository in format 'owner/repo'"},
                            "issue_number": {"type": "integer", "description": "Issue number"},
                            "comment": {"type": "string", "description": "Comment body text"},
                        },
                        "required": ["repo", "issue_number", "comment"],
                    },
                    risk_level=RiskLevel.MEDIUM,
                    requires_approval=False,
                ),
                ToolDefinition(
                    id="github.get_ci_status",
                    connector_id="github",
                    name="get_ci_status",
                    display_name="Inspect CI Workflow Status",
                    description="Check the latest GitHub Actions workflow run status for a repo and branch.",
                    category="dev_tools",
                    input_schema={
                        "type": "object",
                        "properties": {
                            "repo": {"type": "string", "description": "Repository in format 'owner/repo'"},
                            "branch": {"type": "string", "default": "main", "description": "Branch name"},
                        },
                        "required": ["repo"],
                    },
                    risk_level=RiskLevel.LOW,
                    requires_approval=False,
                ),
                ToolDefinition(
                    id="github.merge_pull_request",
                    connector_id="github",
                    name="merge_pull_request",
                    display_name="Merge Pull Request",
                    description="Merge an open Pull Request on GitHub. (High Risk - Requires Approval)",
                    category="dev_tools",
                    input_schema={
                        "type": "object",
                        "properties": {
                            "repo": {"type": "string", "description": "Repository in format 'owner/repo'"},
                            "pull_number": {"type": "integer", "description": "Pull Request number"},
                            "commit_title": {"type": "string", "description": "Optional merge commit title"},
                        },
                        "required": ["repo", "pull_number"],
                    },
                    risk_level=RiskLevel.HIGH,
                    requires_approval=True,
                ),
            ],
        )
        super().__init__(defn)
        self.token = token
        self._mock_issues: list[dict[str, Any]] = [
            {
                "id": 101,
                "number": 42,
                "repo": "vyom/vyom-core",
                "title": "Add dynamic MCP discovery and connector marketplace",
                "state": "open",
                "body": "We need complete support for external connectors and tool execution.",
                "labels": ["enhancement", "core"],
                "created_at": "2026-08-28T10:00:00Z",
            }
        ]

    async def connect(self, credentials: dict[str, Any]) -> dict[str, Any]:
        token = credentials.get("token") or credentials.get("api_key")
        if not token:
            raise ValueError("GitHub Personal Access Token is required")
        self.token = str(token)
        self.status = ConnectorStatus.CONNECTED
        return {"status": "connected", "user": "authenticated_user"}

    async def disconnect(self) -> None:
        self.token = None
        self.status = ConnectorStatus.DISCONNECTED

    async def execute_tool(self, tool_name: str, arguments: dict[str, Any], context: Any = None) -> Any:
        self.validate_input(tool_name, arguments)

        # Live GitHub API if token provided and not in test mockup mode
        if self.token and not self.token.startswith("mock_"):
            return await self._execute_live(tool_name, arguments)
        
        # Test / Offline Mock execution
        return self._execute_mock(tool_name, arguments)

    async def _execute_live(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "Vyom-AI-Assistant/1.0",
        }
        async with httpx.AsyncClient(timeout=15.0) as client:
            if tool_name == "list_repositories":
                user = arguments.get("username")
                url = f"https://api.github.com/users/{user}/repos" if user else "https://api.github.com/user/repos"
                res = await client.get(url, headers=headers)
                return res.json()[:arguments.get("limit", 10)]

            elif tool_name == "search_issues":
                query = arguments["query"]
                res = await client.get(f"https://api.github.com/search/issues?q={query}", headers=headers)
                data = res.json()
                return data.get("items", [])[:arguments.get("limit", 10)]

            elif tool_name == "get_issue":
                repo, num = arguments["repo"], arguments["issue_number"]
                res = await client.get(f"https://api.github.com/repos/{repo}/issues/{num}", headers=headers)
                return res.json()

            elif tool_name == "create_issue":
                repo = arguments["repo"]
                payload = {"title": arguments["title"], "body": arguments.get("body", "")}
                if "labels" in arguments:
                    payload["labels"] = arguments["labels"]
                res = await client.post(f"https://api.github.com/repos/{repo}/issues", headers=headers, json=payload)
                return res.json()

            elif tool_name == "comment_on_issue":
                repo, num = arguments["repo"], arguments["issue_number"]
                res = await client.post(
                    f"https://api.github.com/repos/{repo}/issues/{num}/comments",
                    headers=headers,
                    json={"body": arguments["comment"]},
                )
                return res.json()

            elif tool_name == "get_ci_status":
                repo = arguments["repo"]
                branch = arguments.get("branch", "main")
                res = await client.get(f"https://api.github.com/repos/{repo}/actions/runs?branch={branch}", headers=headers)
                runs = res.json().get("workflow_runs", [])
                return runs[:3]

            elif tool_name == "merge_pull_request":
                repo, num = arguments["repo"], arguments["pull_number"]
                payload = {}
                if "commit_title" in arguments:
                    payload["commit_title"] = arguments["commit_title"]
                res = await client.put(f"https://api.github.com/repos/{repo}/pulls/{num}/merge", headers=headers, json=payload)
                return res.json()

            raise NotImplementedError(f"Tool {tool_name} not supported on GitHub connector")

    def _execute_mock(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        if tool_name == "list_repositories":
            return [
                {"name": "vyom-project", "full_name": "gollyos/vyom-project", "private": True, "stars": 12},
                {"name": "brain-engine", "full_name": "gollyos/brain-engine", "private": False, "stars": 88},
            ]
        elif tool_name == "search_issues":
            return self._mock_issues
        elif tool_name == "get_issue":
            return self._mock_issues[0]
        elif tool_name == "create_issue":
            new_issue = {
                "id": len(self._mock_issues) + 100,
                "number": len(self._mock_issues) + 1,
                "repo": arguments["repo"],
                "title": arguments["title"],
                "body": arguments.get("body", ""),
                "labels": arguments.get("labels", []),
                "state": "open",
                "created_at": "2026-08-28T17:00:00Z",
            }
            self._mock_issues.append(new_issue)
            return new_issue
        elif tool_name == "comment_on_issue":
            return {
                "id": 555,
                "issue_number": arguments["issue_number"],
                "body": arguments["comment"],
                "created_at": "2026-08-28T17:00:00Z",
            }
        elif tool_name == "get_ci_status":
            return [
                {"id": 1234, "name": "CI Tests", "status": "completed", "conclusion": "success", "branch": arguments.get("branch", "main")}
            ]
        elif tool_name == "merge_pull_request":
            return {"merged": True, "message": "Pull Request successfully merged"}
        raise NotImplementedError(f"Mock tool {tool_name} not implemented")
