"""VYOM Universal 300+ Tool Catalog.

Provides a comprehensive, structured catalog of 300+ specialized tool capabilities
spanning 10 major functional domains:
1. Code, Dev & Cloud DevOps (45 tools)
2. Productivity, Docs & Office (40 tools)
3. Communication, Messaging & Social (35 tools)
4. Web Intelligence, Search & Research (35 tools)
5. Media, Image, Audio & Video (30 tools)
6. Desktop & Windows System Control (35 tools)
7. Business, CRM, Marketing & Sales (30 tools)
8. Data Science, AI & Analysis (25 tools)
9. Security, Privacy & Compliance (20 tools)
10. Automation, MCP & Workflows (15 tools)
"""

from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field
from app.schemas.approvals import PermissionLevel


class ToolDefinition(BaseModel):
    """Schema for a capability in the 300+ catalog."""
    id: str
    name: str
    category: str
    description: str
    permission_level: PermissionLevel = PermissionLevel.L1
    risk_level: str = "low"  # low | medium | high | critical
    parameters: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)
    handler_type: str = "builtin"  # builtin | mcp | script | proxy | api


# ---------------------------------------------------------------------------
# DOMAIN 1: Code, Dev & Cloud DevOps (45 Tools)
# ---------------------------------------------------------------------------
DEV_TOOLS = [
    ToolDefinition(id="git_status", name="Git Status", category="dev", description="Inspect working tree status and modified files.", permission_level=PermissionLevel.L0, tags=["git", "vcs", "code"]),
    ToolDefinition(id="git_diff", name="Git Diff", category="dev", description="View file changes and diff patches.", permission_level=PermissionLevel.L0, tags=["git", "diff", "code"]),
    ToolDefinition(id="git_log", name="Git Log", category="dev", description="Inspect commit history and branches.", permission_level=PermissionLevel.L0, tags=["git", "history"]),
    ToolDefinition(id="git_commit", name="Git Commit", category="dev", description="Record changes to the repository with a commit message.", permission_level=PermissionLevel.L1, risk_level="medium", tags=["git", "commit"]),
    ToolDefinition(id="git_branch", name="Git Branch", category="dev", description="List, create, or switch git branches.", permission_level=PermissionLevel.L1, tags=["git", "branch"]),
    ToolDefinition(id="git_push", name="Git Push", category="dev", description="Push local commits to a remote git repository.", permission_level=PermissionLevel.L2, risk_level="high", tags=["git", "remote"]),
    ToolDefinition(id="git_pull", name="Git Pull", category="dev", description="Fetch and integrate remote changes into local branch.", permission_level=PermissionLevel.L1, tags=["git", "remote"]),
    ToolDefinition(id="github_repo_info", name="GitHub Repo Info", category="dev", description="Fetch repository metadata, stargazers, and forks.", permission_level=PermissionLevel.L0, tags=["github", "api"]),
    ToolDefinition(id="github_issue_create", name="GitHub Create Issue", category="dev", description="Create an issue on a GitHub repository.", permission_level=PermissionLevel.L2, tags=["github", "issues"]),
    ToolDefinition(id="github_pr_list", name="GitHub List PRs", category="dev", description="List open and merged pull requests.", permission_level=PermissionLevel.L0, tags=["github", "pull_requests"]),
    ToolDefinition(id="gitlab_project_info", name="GitLab Project Info", category="dev", description="Fetch project info from GitLab instance.", permission_level=PermissionLevel.L0, tags=["gitlab"]),
    ToolDefinition(id="docker_ps", name="Docker List Containers", category="dev", description="List running and stopped Docker containers.", permission_level=PermissionLevel.L0, tags=["docker", "containers"]),
    ToolDefinition(id="docker_logs", name="Docker Container Logs", category="dev", description="Fetch stdout/stderr logs from a container.", permission_level=PermissionLevel.L0, tags=["docker", "logs"]),
    ToolDefinition(id="docker_compose_up", name="Docker Compose Up", category="dev", description="Build and start multi-container application.", permission_level=PermissionLevel.L2, risk_level="high", tags=["docker", "compose"]),
    ToolDefinition(id="k8s_get_pods", name="Kubernetes Get Pods", category="dev", description="List pods in a Kubernetes namespace.", permission_level=PermissionLevel.L0, tags=["kubernetes", "k8s"]),
    ToolDefinition(id="k8s_describe_pod", name="Kubernetes Describe Pod", category="dev", description="View detailed pod state and events.", permission_level=PermissionLevel.L0, tags=["kubernetes", "k8s"]),
    ToolDefinition(id="aws_s3_list", name="AWS S3 List Buckets", category="dev", description="List S3 buckets and object keys.", permission_level=PermissionLevel.L0, tags=["aws", "s3", "cloud"]),
    ToolDefinition(id="aws_s3_upload", name="AWS S3 Upload File", category="dev", description="Upload an artifact to an S3 bucket.", permission_level=PermissionLevel.L2, tags=["aws", "s3"]),
    ToolDefinition(id="aws_lambda_invoke", name="AWS Lambda Invoke", category="dev", description="Invoke an AWS Lambda serverless function.", permission_level=PermissionLevel.L2, tags=["aws", "lambda"]),
    ToolDefinition(id="gcp_gcs_list", name="GCP Cloud Storage List", category="dev", description="List buckets and objects in Google Cloud Storage.", permission_level=PermissionLevel.L0, tags=["gcp", "gcs", "cloud"]),
    ToolDefinition(id="gcp_compute_instances", name="GCP Compute Instances", category="dev", description="List active Google Compute Engine VMs.", permission_level=PermissionLevel.L0, tags=["gcp", "vm"]),
    ToolDefinition(id="azure_blob_list", name="Azure Blob Storage List", category="dev", description="List containers and blobs in Azure Storage.", permission_level=PermissionLevel.L0, tags=["azure", "storage"]),
    ToolDefinition(id="npm_install", name="npm Install Package", category="dev", description="Install node modules dependencies via npm.", permission_level=PermissionLevel.L1, tags=["npm", "node"]),
    ToolDefinition(id="npm_run_script", name="npm Run Script", category="dev", description="Execute package.json scripts (build, test, dev).", permission_level=PermissionLevel.L1, tags=["npm", "scripts"]),
    ToolDefinition(id="pip_install", name="pip Install Package", category="dev", description="Install Python packages into virtualenv.", permission_level=PermissionLevel.L1, tags=["python", "pip"]),
    ToolDefinition(id="python_repl", name="Python REPL Executor", category="dev", description="Evaluate a Python expression or code snippet in a sandbox.", permission_level=PermissionLevel.L1, tags=["python", "eval"]),
    ToolDefinition(id="node_repl", name="Node.js REPL Executor", category="dev", description="Evaluate JavaScript expression in isolated context.", permission_level=PermissionLevel.L1, tags=["javascript", "node"]),
    ToolDefinition(id="sqlite_query", name="SQLite Query", category="dev", description="Execute read-only SQL queries on a local SQLite database.", permission_level=PermissionLevel.L0, tags=["sql", "sqlite", "database"]),
    ToolDefinition(id="sqlite_schema", name="SQLite Schema Inspector", category="dev", description="Inspect tables, columns, indexes, and triggers.", permission_level=PermissionLevel.L0, tags=["sql", "sqlite", "schema"]),
    ToolDefinition(id="postgres_query", name="PostgreSQL Query", category="dev", description="Execute query on a connected PostgreSQL instance.", permission_level=PermissionLevel.L0, tags=["sql", "postgres"]),
    ToolDefinition(id="mysql_query", name="MySQL Query", category="dev", description="Execute query on a MySQL database.", permission_level=PermissionLevel.L0, tags=["sql", "mysql"]),
    ToolDefinition(id="redis_get", name="Redis Key Lookup", category="dev", description="Get key value or hash from Redis cache.", permission_level=PermissionLevel.L0, tags=["redis", "cache"]),
    ToolDefinition(id="mongodb_find", name="MongoDB Find Documents", category="dev", description="Query MongoDB collection with filter.", permission_level=PermissionLevel.L0, tags=["mongodb", "nosql"]),
    ToolDefinition(id="graphql_query", name="GraphQL Client Query", category="dev", description="Send query or mutation to a GraphQL endpoint.", permission_level=PermissionLevel.L1, tags=["graphql", "api"]),
    ToolDefinition(id="jq_json_filter", name="jq JSON Transformer", category="dev", description="Filter, slice, and transform JSON data using jq syntax.", permission_level=PermissionLevel.L0, tags=["json", "jq"]),
    ToolDefinition(id="code_linter", name="Code Linter", category="dev", description="Run flake8, eslint, or ruff on project files.", permission_level=PermissionLevel.L0, tags=["lint", "code_quality"]),
    ToolDefinition(id="code_formatter", name="Code Formatter", category="dev", description="Format code with black, prettier, or rustfmt.", permission_level=PermissionLevel.L1, tags=["format", "prettier"]),
    ToolDefinition(id="pytest_runner", name="Pytest Test Runner", category="dev", description="Run discovered pytest test files and collect results.", permission_level=PermissionLevel.L1, tags=["test", "pytest"]),
    ToolDefinition(id="ast_parser", name="AST Syntax Tree Parser", category="dev", description="Inspect Python/JS AST symbols, functions, and classes.", permission_level=PermissionLevel.L0, tags=["ast", "symbols"]),
    ToolDefinition(id="dep_audit", name="Dependency Vulnerability Audit", category="dev", description="Scan pip/npm packages for known CVE vulnerabilities.", permission_level=PermissionLevel.L0, tags=["security", "audit"]),
    ToolDefinition(id="http_curl", name="HTTP Curl Request", category="dev", description="Perform GET/POST/PUT HTTP requests with custom headers.", permission_level=PermissionLevel.L1, tags=["http", "api", "curl"]),
    ToolDefinition(id="dns_lookup", name="DNS Record Lookup", category="dev", description="Query A, AAAA, CNAME, MX, TXT records for a domain.", permission_level=PermissionLevel.L0, tags=["dns", "network"]),
    ToolDefinition(id="ssl_cert_check", name="SSL Certificate Inspector", category="dev", description="Inspect certificate validity, issuer, and expiry date.", permission_level=PermissionLevel.L0, tags=["ssl", "security"]),
    ToolDefinition(id="ping_host", name="Ping Host Latency", category="dev", description="Measure network round-trip time in milliseconds.", permission_level=PermissionLevel.L0, tags=["network", "ping"]),
    ToolDefinition(id="regex_tester", name="Regex Pattern Matcher", category="dev", description="Test regular expressions against sample text.", permission_level=PermissionLevel.L0, tags=["regex", "text"]),
]

# ---------------------------------------------------------------------------
# DOMAIN 2: Productivity, Docs & Office (40 Tools)
# ---------------------------------------------------------------------------
PRODUCTIVITY_TOOLS = [
    ToolDefinition(id="notion_read_page", name="Notion Read Page", category="productivity", description="Fetch page content and properties from Notion.", permission_level=PermissionLevel.L0, tags=["notion", "docs"]),
    ToolDefinition(id="notion_create_page", name="Notion Create Page", category="productivity", description="Create a new page or database entry in Notion.", permission_level=PermissionLevel.L2, tags=["notion", "docs"]),
    ToolDefinition(id="obsidian_vault_search", name="Obsidian Vault Search", category="productivity", description="Search Markdown notes across local vault.", permission_level=PermissionLevel.L0, tags=["obsidian", "markdown"]),
    ToolDefinition(id="obsidian_note_create", name="Obsidian Note Create", category="productivity", description="Write a Markdown note with YAML frontmatter to vault.", permission_level=PermissionLevel.L1, tags=["obsidian", "notes"]),
    ToolDefinition(id="gdocs_read", name="Google Docs Read", category="productivity", description="Fetch document body and headings from Google Docs.", permission_level=PermissionLevel.L0, tags=["google", "docs"]),
    ToolDefinition(id="gdocs_write", name="Google Docs Write", category="productivity", description="Create or append text to Google Doc.", permission_level=PermissionLevel.L2, tags=["google", "docs"]),
    ToolDefinition(id="gsheets_read", name="Google Sheets Read", category="productivity", description="Read spreadsheet values by range or sheet name.", permission_level=PermissionLevel.L0, tags=["google", "sheets"]),
    ToolDefinition(id="gsheets_append", name="Google Sheets Append Row", category="productivity", description="Append rows of data into Google Spreadsheet.", permission_level=PermissionLevel.L2, tags=["google", "sheets"]),
    ToolDefinition(id="gdrive_search", name="Google Drive Search", category="productivity", description="Search files by name, type, or modified date.", permission_level=PermissionLevel.L0, tags=["google", "drive"]),
    ToolDefinition(id="docx_create", name="Word DOCX Generator", category="productivity", description="Generate formatted Microsoft Word .docx documents.", permission_level=PermissionLevel.L1, tags=["office", "word", "docx"]),
    ToolDefinition(id="docx_read", name="Word DOCX Reader", category="productivity", description="Extract paragraphs, tables, and text from .docx file.", permission_level=PermissionLevel.L0, tags=["office", "word", "docx"]),
    ToolDefinition(id="xlsx_create", name="Excel XLSX Generator", category="productivity", description="Create multi-sheet Excel workbooks with formulas.", permission_level=PermissionLevel.L1, tags=["office", "excel", "xlsx"]),
    ToolDefinition(id="xlsx_read", name="Excel XLSX Reader", category="productivity", description="Extract sheet data from Excel spreadsheets.", permission_level=PermissionLevel.L0, tags=["office", "excel", "xlsx"]),
    ToolDefinition(id="pptx_create", name="PowerPoint PPTX Generator", category="productivity", description="Generate slide decks from outlines and bullet points.", permission_level=PermissionLevel.L1, tags=["office", "powerpoint", "pptx"]),
    ToolDefinition(id="pdf_read_text", name="PDF Text Extractor", category="productivity", description="Extract text content and metadata from PDF files.", permission_level=PermissionLevel.L0, tags=["pdf", "ocr"]),
    ToolDefinition(id="pdf_merge", name="PDF Merger", category="productivity", description="Merge multiple PDF files into one combined document.", permission_level=PermissionLevel.L1, tags=["pdf"]),
    ToolDefinition(id="pdf_split", name="PDF Splitter", category="productivity", description="Split PDF into individual pages or page ranges.", permission_level=PermissionLevel.L1, tags=["pdf"]),
    ToolDefinition(id="pdf_ocr", name="PDF OCR Reader", category="productivity", description="Extract text from scanned PDF images using OCR.", permission_level=PermissionLevel.L0, tags=["pdf", "ocr"]),
    ToolDefinition(id="csv_to_json", name="CSV to JSON Converter", category="productivity", description="Convert CSV tables into structured JSON lists.", permission_level=PermissionLevel.L0, tags=["csv", "json"]),
    ToolDefinition(id="markdown_to_html", name="Markdown to HTML Compiler", category="productivity", description="Compile markdown to styled HTML with table support.", permission_level=PermissionLevel.L0, tags=["markdown", "html"]),
    ToolDefinition(id="latex_render", name="LaTeX Equation Renderer", category="productivity", description="Render mathematical formulas from LaTeX to PNG/SVG.", permission_level=PermissionLevel.L0, tags=["latex", "math"]),
    ToolDefinition(id="todoist_list_tasks", name="Todoist List Tasks", category="productivity", description="Fetch active tasks from Todoist project.", permission_level=PermissionLevel.L0, tags=["todoist", "tasks"]),
    ToolDefinition(id="todoist_create_task", name="Todoist Create Task", category="productivity", description="Create task with due date and priority in Todoist.", permission_level=PermissionLevel.L2, tags=["todoist", "tasks"]),
    ToolDefinition(id="trello_list_cards", name="Trello List Cards", category="productivity", description="Fetch cards from Trello board list.", permission_level=PermissionLevel.L0, tags=["trello", "kanban"]),
    ToolDefinition(id="trello_create_card", name="Trello Create Card", category="productivity", description="Add new card to Trello list.", permission_level=PermissionLevel.L2, tags=["trello", "kanban"]),
    ToolDefinition(id="asana_list_tasks", name="Asana List Tasks", category="productivity", description="List tasks assigned to user in Asana.", permission_level=PermissionLevel.L0, tags=["asana", "tasks"]),
    ToolDefinition(id="jira_issue_get", name="Jira Issue Inspector", category="productivity", description="Get issue status, assignee, and comments from Jira.", permission_level=PermissionLevel.L0, tags=["jira", "scrum"]),
    ToolDefinition(id="jira_issue_create", name="Jira Issue Create", category="productivity", description="Create ticket in Jira sprint backlog.", permission_level=PermissionLevel.L2, tags=["jira", "scrum"]),
    ToolDefinition(id="linear_issue_create", name="Linear Create Issue", category="productivity", description="Create issue on Linear project board.", permission_level=PermissionLevel.L2, tags=["linear", "dev"]),
    ToolDefinition(id="clickup_list_tasks", name="ClickUp List Tasks", category="productivity", description="Fetch tasks from ClickUp folder or list.", permission_level=PermissionLevel.L0, tags=["clickup"]),
    ToolDefinition(id="gcalendar_list_events", name="Google Calendar List Events", category="productivity", description="List upcoming meetings and agenda items.", permission_level=PermissionLevel.L0, tags=["calendar", "schedule"]),
    ToolDefinition(id="gcalendar_create_event", name="Google Calendar Create Event", category="productivity", description="Schedule new meeting on Google Calendar.", permission_level=PermissionLevel.L2, tags=["calendar", "schedule"]),
    ToolDefinition(id="outlook_calendar_list", name="Outlook Calendar List", category="productivity", description="Fetch upcoming Outlook calendar appointments.", permission_level=PermissionLevel.L0, tags=["outlook", "calendar"]),
    ToolDefinition(id="timezone_convert", name="Timezone Converter", category="productivity", description="Convert date and time between global timezones.", permission_level=PermissionLevel.L0, tags=["time", "timezone"]),
    ToolDefinition(id="pomodoro_timer", name="Pomodoro Focus Timer", category="productivity", description="Start or inspect a structured 25m focus sprint.", permission_level=PermissionLevel.L0, tags=["focus", "timer"]),
    ToolDefinition(id="habit_log_checkin", name="Habit Tracker Check-in", category="productivity", description="Log completion of daily habit or routine.", permission_level=PermissionLevel.L1, tags=["habit", "tracking"]),
    ToolDefinition(id="daily_journal_entry", name="Daily Journal Logger", category="productivity", description="Append reflections or logs to daily journal note.", permission_level=PermissionLevel.L1, tags=["journal", "notes"]),
    ToolDefinition(id="meeting_notes_summarizer", name="Meeting Notes Summarizer", category="productivity", description="Extract action items and key decisions from transcript.", permission_level=PermissionLevel.L0, tags=["meeting", "summary"]),
    ToolDefinition(id="readability_analyzer", name="Readability Score Analyzer", category="productivity", description="Calculate Flesch-Kincaid grade and readability score.", permission_level=PermissionLevel.L0, tags=["writing", "analysis"]),
    ToolDefinition(id="citation_formatter", name="Citation Formatter", category="productivity", description="Format academic/web sources into APA, MLA, or IEEE format.", permission_level=PermissionLevel.L0, tags=["citation", "research"]),
]

# ---------------------------------------------------------------------------
# DOMAIN 3: Communication, Messaging & Social (35 Tools)
# ---------------------------------------------------------------------------
COMMUNICATION_TOOLS = [
    ToolDefinition(id="whatsapp_send_msg", name="WhatsApp Send Message", category="communication", description="Send WhatsApp text message to phone number.", permission_level=PermissionLevel.L2, risk_level="medium", tags=["whatsapp", "messaging"]),
    ToolDefinition(id="whatsapp_make_call", name="WhatsApp Call", category="communication", description="Initiate WhatsApp voice or video call.", permission_level=PermissionLevel.L2, risk_level="high", tags=["whatsapp", "call"]),
    ToolDefinition(id="telegram_send_msg", name="Telegram Send Message", category="communication", description="Send message to Telegram chat or channel.", permission_level=PermissionLevel.L2, tags=["telegram", "bot"]),
    ToolDefinition(id="telegram_send_photo", name="Telegram Send Photo", category="communication", description="Send image file to Telegram conversation.", permission_level=PermissionLevel.L2, tags=["telegram", "media"]),
    ToolDefinition(id="discord_send_msg", name="Discord Send Message", category="communication", description="Post message to Discord channel via Bot/Webhook.", permission_level=PermissionLevel.L2, tags=["discord", "bot"]),
    ToolDefinition(id="discord_webhook_post", name="Discord Webhook Dispatcher", category="communication", description="Send rich embed message to Discord webhook URL.", permission_level=PermissionLevel.L2, tags=["discord", "webhook"]),
    ToolDefinition(id="slack_send_msg", name="Slack Send Message", category="communication", description="Post message to Slack channel.", permission_level=PermissionLevel.L2, tags=["slack"]),
    ToolDefinition(id="slack_reply_thread", name="Slack Reply in Thread", category="communication", description="Reply to an existing Slack message thread.", permission_level=PermissionLevel.L2, tags=["slack"]),
    ToolDefinition(id="email_send_gmail", name="Gmail Send Email", category="communication", description="Send email via Gmail SMTP / OAuth provider.", permission_level=PermissionLevel.L2, risk_level="high", tags=["email", "gmail"]),
    ToolDefinition(id="email_read_inbox", name="Email Inbox Search", category="communication", description="Search incoming emails by sender, subject, or date.", permission_level=PermissionLevel.L0, tags=["email", "imap"]),
    ToolDefinition(id="email_draft_create", name="Email Create Draft", category="communication", description="Save draft email without sending.", permission_level=PermissionLevel.L1, tags=["email", "draft"]),
    ToolDefinition(id="email_send_outlook", name="Outlook Send Email", category="communication", description="Send email via Microsoft Outlook / Graph API.", permission_level=PermissionLevel.L2, risk_level="high", tags=["email", "outlook"]),
    ToolDefinition(id="sms_twilio_send", name="Twilio Send SMS", category="communication", description="Send SMS text message via Twilio API.", permission_level=PermissionLevel.L2, risk_level="high", tags=["sms", "twilio"]),
    ToolDefinition(id="call_twilio_make", name="Twilio Voice Call", category="communication", description="Initiate outbound voice phone call with TwiML speech.", permission_level=PermissionLevel.L2, risk_level="critical", tags=["phone", "twilio"]),
    ToolDefinition(id="linkedin_post_update", name="LinkedIn Post Update", category="communication", description="Publish post to personal or company LinkedIn page.", permission_level=PermissionLevel.L2, tags=["linkedin", "social"]),
    ToolDefinition(id="linkedin_search_profile", name="LinkedIn Search Profiles", category="communication", description="Search public profiles and recruiters on LinkedIn.", permission_level=PermissionLevel.L0, tags=["linkedin", "recruiting"]),
    ToolDefinition(id="twitter_post_tweet", name="Twitter/X Post Tweet", category="communication", description="Post a tweet or thread to Twitter / X.", permission_level=PermissionLevel.L2, tags=["twitter", "x", "social"]),
    ToolDefinition(id="twitter_search_recent", name="Twitter/X Search Tweets", category="communication", description="Search recent tweets by hashtag or keyword.", permission_level=PermissionLevel.L0, tags=["twitter", "search"]),
    ToolDefinition(id="instagram_post_photo", name="Instagram Post Photo", category="communication", description="Publish photo with caption to Instagram.", permission_level=PermissionLevel.L2, tags=["instagram", "social"]),
    ToolDefinition(id="facebook_post_feed", name="Facebook Post Feed", category="communication", description="Post update to Facebook page feed.", permission_level=PermissionLevel.L2, tags=["facebook", "social"]),
    ToolDefinition(id="meta_ads_list_campaigns", name="Meta Ads List Campaigns", category="communication", description="Fetch active Facebook/Instagram ad campaigns.", permission_level=PermissionLevel.L0, tags=["meta_ads", "marketing"]),
    ToolDefinition(id="reddit_search_posts", name="Reddit Search Posts", category="communication", description="Search discussions and threads in subreddits.", permission_level=PermissionLevel.L0, tags=["reddit", "community"]),
    ToolDefinition(id="reddit_post_submission", name="Reddit Create Post", category="communication", description="Submit post to specified subreddit.", permission_level=PermissionLevel.L2, tags=["reddit", "community"]),
    ToolDefinition(id="zoom_create_meeting", name="Zoom Create Meeting", category="communication", description="Generate Zoom meeting link and passcode.", permission_level=PermissionLevel.L2, tags=["zoom", "meeting"]),
    ToolDefinition(id="gmeet_create_link", name="Google Meet Generator", category="communication", description="Generate Google Meet video link.", permission_level=PermissionLevel.L1, tags=["google", "meet"]),
    ToolDefinition(id="teams_send_msg", name="Microsoft Teams Send Message", category="communication", description="Send message to Teams channel.", permission_level=PermissionLevel.L2, tags=["teams", "microsoft"]),
    ToolDefinition(id="intercom_send_msg", name="Intercom Send User Message", category="communication", description="Send message to customer on Intercom.", permission_level=PermissionLevel.L2, tags=["intercom", "support"]),
    ToolDefinition(id="zendesk_create_ticket", name="Zendesk Create Ticket", category="communication", description="Create customer support ticket in Zendesk.", permission_level=PermissionLevel.L2, tags=["zendesk", "support"]),
    ToolDefinition(id="mailchimp_add_subscriber", name="Mailchimp Add Subscriber", category="communication", description="Add email to Mailchimp marketing audience list.", permission_level=PermissionLevel.L2, tags=["mailchimp", "marketing"]),
    ToolDefinition(id="sendgrid_send_template", name="SendGrid Send Template Email", category="communication", description="Send transactional email via SendGrid dynamic template.", permission_level=PermissionLevel.L2, tags=["sendgrid", "email"]),
    ToolDefinition(id="youtube_post_comment", name="YouTube Post Comment", category="communication", description="Post comment on a YouTube video.", permission_level=PermissionLevel.L2, tags=["youtube"]),
    ToolDefinition(id="youtube_search_videos", name="YouTube Search Videos", category="communication", description="Search YouTube videos by query and fetch metadata.", permission_level=PermissionLevel.L0, tags=["youtube", "media"]),
    ToolDefinition(id="discourse_create_topic", name="Discourse Create Topic", category="communication", description="Create a new topic thread on Discourse community.", permission_level=PermissionLevel.L2, tags=["discourse", "community"]),
    ToolDefinition(id="customerio_track_event", name="Customer.io Track Event", category="communication", description="Track user interaction event in Customer.io.", permission_level=PermissionLevel.L1, tags=["customerio", "analytics"]),
    ToolDefinition(id="unread_notifications_check", name="Unread Communications Check", category="communication", description="Scan across connected channels for unread priority messages.", permission_level=PermissionLevel.L0, tags=["inbox", "notifications"]),
]

# ---------------------------------------------------------------------------
# DOMAIN 4: Web Intelligence, Search & Research (35 Tools)
# ---------------------------------------------------------------------------
RESEARCH_TOOLS = [
    ToolDefinition(id="wikipedia_summary", name="Wikipedia Summary", category="research", description="Fetch factual summary of topic from Wikipedia.", permission_level=PermissionLevel.L0, tags=["wikipedia", "encyclopedia"]),
    ToolDefinition(id="wikipedia_search", name="Wikipedia Search", category="research", description="Search Wikipedia articles by keyword.", permission_level=PermissionLevel.L0, tags=["wikipedia"]),
    ToolDefinition(id="news_top_headlines", name="News Top Headlines", category="research", description="Fetch live breaking top news headlines.", permission_level=PermissionLevel.L0, tags=["news", "rss"]),
    ToolDefinition(id="news_topic_search", name="News Topic Search", category="research", description="Search current news articles on specific topic.", permission_level=PermissionLevel.L0, tags=["news", "search"]),
    ToolDefinition(id="duckduckgo_search", name="DuckDuckGo Web Search", category="research", description="Privacy-preserving web search for links and snippets.", permission_level=PermissionLevel.L0, tags=["search", "web"]),
    ToolDefinition(id="brave_web_search", name="Brave Search", category="research", description="Search web via Brave Search API index.", permission_level=PermissionLevel.L0, tags=["search", "brave"]),
    ToolDefinition(id="tavily_ai_search", name="Tavily AI Search", category="research", description="Search web for LLM-optimized grounded research facts.", permission_level=PermissionLevel.L0, tags=["search", "ai_search"]),
    ToolDefinition(id="serpapi_google_search", name="SerpAPI Google Search", category="research", description="Scrape Google search SERP results and knowledge panel.", permission_level=PermissionLevel.L0, tags=["google", "serp"]),
    ToolDefinition(id="perplexity_search", name="Perplexity Search", category="research", description="Grounded multi-source research with source citations.", permission_level=PermissionLevel.L0, tags=["perplexity", "ai"]),
    ToolDefinition(id="arxiv_search_papers", name="ArXiv Paper Finder", category="research", description="Search scientific research papers on ArXiv.", permission_level=PermissionLevel.L0, tags=["arxiv", "science"]),
    ToolDefinition(id="pubmed_search_medical", name="PubMed Medical Search", category="research", description="Search biomedical and clinical studies on PubMed.", permission_level=PermissionLevel.L0, tags=["pubmed", "health"]),
    ToolDefinition(id="hackernews_top", name="HackerNews Top Stories", category="research", description="Fetch top trending technology stories and discussions.", permission_level=PermissionLevel.L0, tags=["hackernews", "tech"]),
    ToolDefinition(id="producthunt_today", name="ProductHunt Trending Today", category="research", description="Fetch top newly launched products of the day.", permission_level=PermissionLevel.L0, tags=["producthunt", "startups"]),
    ToolDefinition(id="github_trending", name="GitHub Trending Repositories", category="research", description="Fetch trending open-source repositories by language.", permission_level=PermissionLevel.L0, tags=["github", "trending"]),
    ToolDefinition(id="crunchbase_company_lookup", name="Crunchbase Company Lookup", category="research", description="Fetch funding, founders, and headcount from Crunchbase.", permission_level=PermissionLevel.L0, tags=["crunchbase", "b2b"]),
    ToolDefinition(id="wayback_machine_lookup", name="Wayback Machine Archive", category="research", description="Retrieve archived historical snapshots of a webpage.", permission_level=PermissionLevel.L0, tags=["archive", "history"]),
    ToolDefinition(id="rss_feed_reader", name="RSS / Atom Feed Reader", category="research", description="Parse and fetch latest articles from any RSS feed URL.", permission_level=PermissionLevel.L0, tags=["rss", "reader"]),
    ToolDefinition(id="sitemap_crawler", name="Sitemap XML Crawler", category="research", description="Extract all URLs indexed in a website sitemap.", permission_level=PermissionLevel.L0, tags=["sitemap", "seo"]),
    ToolDefinition(id="webpage_markdown_extractor", name="Webpage Reader (Markdown)", category="research", description="Extract main clean text content from URL as Markdown.", permission_level=PermissionLevel.L0, tags=["scraper", "reader"]),
    ToolDefinition(id="metadata_scraper", name="OpenGraph Metadata Scraper", category="research", description="Extract title, og:image, description from URL.", permission_level=PermissionLevel.L0, tags=["opengraph", "meta"]),
    ToolDefinition(id="schema_org_parser", name="Schema.org JSON-LD Parser", category="research", description="Extract structured JSON-LD entities from webpage.", permission_level=PermissionLevel.L0, tags=["seo", "jsonld"]),
    ToolDefinition(id="fact_checker_verifier", name="Fact Checker & Verifier", category="research", description="Cross-verify statement against multiple indexed sources.", permission_level=PermissionLevel.L0, tags=["verification", "facts"]),
    ToolDefinition(id="contradiction_detector", name="Contradiction Detector", category="research", description="Identify conflicting statements across research notes.", permission_level=PermissionLevel.L0, tags=["analysis", "logic"]),
    ToolDefinition(id="source_credibility_scorer", name="Source Credibility Scorer", category="research", description="Score domain trustworthiness and authoritative ranking.", permission_level=PermissionLevel.L0, tags=["trust", "ranking"]),
    ToolDefinition(id="stock_quote_lookup", name="Stock Market Quote Lookup", category="research", description="Fetch current stock price, volume, and day range.", permission_level=PermissionLevel.L0, tags=["finance", "stocks"]),
    ToolDefinition(id="crypto_price_tracker", name="Crypto Price Tracker", category="research", description="Fetch Bitcoin, Ethereum, Solana prices and 24h change.", permission_level=PermissionLevel.L0, tags=["crypto", "web3"]),
    ToolDefinition(id="forex_currency_rate", name="Currency Exchange Rate", category="research", description="Get real-time exchange rates (USD, INR, EUR, GBP).", permission_level=PermissionLevel.L0, tags=["forex", "currency"]),
    ToolDefinition(id="weather_current_forecast", name="Open-Meteo Weather Forecast", category="research", description="Get current temperature, humidity, and 7-day forecast.", permission_level=PermissionLevel.L0, tags=["weather", "forecast"]),
    ToolDefinition(id="air_quality_index", name="Air Quality Index (AQI)", category="research", description="Fetch PM2.5, PM10, and AQI rating for city.", permission_level=PermissionLevel.L0, tags=["environment", "aqi"]),
    ToolDefinition(id="flight_tracker", name="Flight Status Tracker", category="research", description="Check flight schedule, delay, and gate info.", permission_level=PermissionLevel.L0, tags=["travel", "flight"]),
    ToolDefinition(id="package_tracking_lookup", name="Package Shipment Tracker", category="research", description="Track delivery status across courier tracking numbers.", permission_level=PermissionLevel.L0, tags=["logistics", "shipping"]),
    ToolDefinition(id="geocode_address", name="Map Geocoding", category="research", description="Convert street address to latitude/longitude coordinates.", permission_level=PermissionLevel.L0, tags=["map", "gis"]),
    ToolDefinition(id="distance_matrix_calc", name="Distance Matrix Calculator", category="research", description="Calculate driving distance and ETA between locations.", permission_level=PermissionLevel.L0, tags=["maps", "navigation"]),
    ToolDefinition(id="trivia_facts_lookup", name="Trivia & Knowledge Facts", category="research", description="Fetch verified historical, science, or general trivia facts.", permission_level=PermissionLevel.L0, tags=["trivia", "facts"]),
    ToolDefinition(id="patent_search", name="Google Patents Search", category="research", description="Search patent filings and prior art.", permission_level=PermissionLevel.L0, tags=["patents", "ip"]),
]

# ---------------------------------------------------------------------------
# DOMAIN 5: Media, Image, Audio & Video (30 Tools)
# ---------------------------------------------------------------------------
MEDIA_TOOLS = [
    ToolDefinition(id="ffmpeg_render_video", name="FFmpeg Video Render", category="media", description="Compile image frames, audio, and captions into MP4 video.", permission_level=PermissionLevel.L1, tags=["video", "ffmpeg", "render"]),
    ToolDefinition(id="ffmpeg_extract_audio", name="FFmpeg Extract Audio", category="media", description="Extract MP3/WAV audio track from video file.", permission_level=PermissionLevel.L1, tags=["video", "audio", "ffmpeg"]),
    ToolDefinition(id="ffmpeg_trim_video", name="FFmpeg Trim Video", category="media", description="Cut video segment between start and end timestamps.", permission_level=PermissionLevel.L1, tags=["video", "edit"]),
    ToolDefinition(id="ffmpeg_compress_video", name="FFmpeg Video Compressor", category="media", description="Compress video bitrate using H.264/CRF28.", permission_level=PermissionLevel.L1, tags=["video", "compress"]),
    ToolDefinition(id="edge_tts_speak", name="Edge-TTS Voice Synthesizer", category="media", description="Generate high-quality MP3 voice narration from text (no-key).", permission_level=PermissionLevel.L0, tags=["tts", "voice", "audio"]),
    ToolDefinition(id="elevenlabs_tts", name="ElevenLabs Voice Generator", category="media", description="Generate hyper-realistic voiceover using ElevenLabs API.", permission_level=PermissionLevel.L1, tags=["tts", "elevenlabs", "voice"]),
    ToolDefinition(id="whisper_stt_transcribe", name="Whisper Speech-to-Text", category="media", description="Transcribe audio file to text transcript with timestamps.", permission_level=PermissionLevel.L0, tags=["stt", "whisper", "audio"]),
    ToolDefinition(id="image_resize_crop", name="Image Resize & Crop", category="media", description="Resize, crop, and pad image dimensions with Pillow.", permission_level=PermissionLevel.L1, tags=["image", "pillow"]),
    ToolDefinition(id="image_compress_opt", name="Image Compressor", category="media", description="Optimize JPEG/PNG/WebP file size with lossless compression.", permission_level=PermissionLevel.L1, tags=["image", "optimize"]),
    ToolDefinition(id="image_format_convert", name="Image Format Converter", category="media", description="Convert between PNG, JPEG, WebP, BMP, and ICO formats.", permission_level=PermissionLevel.L1, tags=["image", "convert"]),
    ToolDefinition(id="image_watermark", name="Image Watermark Applier", category="media", description="Apply logo or text watermark overlay to image.", permission_level=PermissionLevel.L1, tags=["image", "watermark"]),
    ToolDefinition(id="rembg_remove_background", name="AI Background Remover", category="media", description="Remove image background using U2Net / Rembg model.", permission_level=PermissionLevel.L1, tags=["image", "rembg", "ai"]),
    ToolDefinition(id="pillow_filter_adjust", name="Image Contrast & Color Adjust", category="media", description="Adjust brightness, contrast, sharpness, and color saturation.", permission_level=PermissionLevel.L1, tags=["image", "filter"]),
    ToolDefinition(id="qrcode_generate", name="QR Code Generator", category="media", description="Generate custom QR code PNG from text or URL.", permission_level=PermissionLevel.L0, tags=["qrcode", "generator"]),
    ToolDefinition(id="barcode_read", name="Barcode / QR Reader", category="media", description="Decode QR code or barcode from image file.", permission_level=PermissionLevel.L0, tags=["barcode", "ocr"]),
    ToolDefinition(id="svg_to_png", name="SVG to PNG Rasterizer", category="media", description="Render vector SVG into high-resolution PNG image.", permission_level=PermissionLevel.L0, tags=["svg", "vector"]),
    ToolDefinition(id="exif_metadata_strip", name="EXIF Privacy Stripper", category="media", description="Remove GPS coordinates and device metadata from image.", permission_level=PermissionLevel.L1, tags=["privacy", "exif"]),
    ToolDefinition(id="video_scene_detect", name="Video Scene Splitter", category="media", description="Detect scene transitions and split video into chapters.", permission_level=PermissionLevel.L1, tags=["video", "scenes"]),
    ToolDefinition(id="subtitle_srt_generate", name="Subtitle SRT Generator", category="media", description="Generate timed .srt subtitle file from audio transcription.", permission_level=PermissionLevel.L1, tags=["video", "subtitles"]),
    ToolDefinition(id="audio_noise_suppress", name="Audio Noise Suppressor", category="media", description="Clean background hiss and static from voice recordings.", permission_level=PermissionLevel.L1, tags=["audio", "cleanup"]),
    ToolDefinition(id="palette_color_extract", name="Dominant Color Palette Extractor", category="media", description="Extract top 5 hex color codes from image.", permission_level=PermissionLevel.L0, tags=["design", "colors"]),
    ToolDefinition(id="gif_creator_frames", name="Animated GIF Builder", category="media", description="Create animated GIF from list of image frames.", permission_level=PermissionLevel.L1, tags=["gif", "animation"]),
    ToolDefinition(id="screen_recorder_clip", name="Desktop Screen Recorder", category="media", description="Record desktop screen region to MP4 clip.", permission_level=PermissionLevel.L2, tags=["screen", "recording"]),
    ToolDefinition(id="audio_spectrogram_plot", name="Audio Spectrogram Generator", category="media", description="Generate visual frequency spectrogram plot from audio.", permission_level=PermissionLevel.L0, tags=["audio", "visual"]),
    ToolDefinition(id="audio_concat_merge", name="Audio Track Concatenator", category="media", description="Merge multiple audio clips into a single track.", permission_level=PermissionLevel.L1, tags=["audio", "merge"]),
    ToolDefinition(id="video_thumbnail_extract", name="Video Thumbnail Grabber", category="media", description="Extract high-res frame at specified timestamp.", permission_level=PermissionLevel.L0, tags=["video", "thumbnail"]),
    ToolDefinition(id="font_metadata_inspect", name="Font TTF Inspector", category="media", description="Inspect glyphs, weight, and metadata of TTF/OTF font.", permission_level=PermissionLevel.L0, tags=["font", "typography"]),
    ToolDefinition(id="media_duration_probe", name="FFprobe Media Inspector", category="media", description="Get exact duration, resolution, codecs, and fps of file.", permission_level=PermissionLevel.L0, tags=["media", "ffprobe"]),
    ToolDefinition(id="audio_volume_normalize", name="Audio Normalizer (EBU R128)", category="media", description="Normalize audio loudness across tracks.", permission_level=PermissionLevel.L1, tags=["audio", "mastering"]),
    ToolDefinition(id="lofi_beat_player", name="Lofi Background Stream", category="media", description="Play ambient focus background lofi track.", permission_level=PermissionLevel.L1, tags=["music", "lofi"]),
]

# ---------------------------------------------------------------------------
# DOMAIN 6: Desktop & Windows System Control (35 Tools)
# ---------------------------------------------------------------------------
SYSTEM_TOOLS = [
    ToolDefinition(id="battery_status", name="Battery Status Monitor", category="system", description="Check battery percentage, charging state, and remaining runtime.", permission_level=PermissionLevel.L0, tags=["system", "battery", "hardware"]),
    ToolDefinition(id="volume_control", name="Master Volume Controller", category="system", description="Set master audio volume level (0-100), mute, or unmute.", permission_level=PermissionLevel.L1, tags=["system", "audio", "volume"]),
    ToolDefinition(id="lock_workstation", name="Lock Workstation", category="system", description="Instantly lock the Windows desktop session.", permission_level=PermissionLevel.L1, tags=["system", "security", "lock"]),
    ToolDefinition(id="screen_observe", name="Active Screen Observer", category="system", description="Capture active screen and parse UI elements semantically.", permission_level=PermissionLevel.L0, tags=["screen", "vision"]),
    ToolDefinition(id="screenshot_capture", name="Screenshot Capture", category="system", description="Take PNG screenshot of primary or selected monitor.", permission_level=PermissionLevel.L0, tags=["screen", "screenshot"]),
    ToolDefinition(id="window_list_active", name="Window List Inspector", category="system", description="List all open windows, titles, and PIDs.", permission_level=PermissionLevel.L0, tags=["window", "processes"]),
    ToolDefinition(id="window_focus", name="Window Focus Switcher", category="system", description="Bring specified window title to foreground.", permission_level=PermissionLevel.L1, tags=["window", "focus"]),
    ToolDefinition(id="window_resize_move", name="Window Resize & Move", category="system", description="Position window at (x, y) with specified width and height.", permission_level=PermissionLevel.L1, tags=["window", "layout"]),
    ToolDefinition(id="window_minimize_all", name="Minimize All Windows (Show Desktop)", category="system", description="Minimize all active desktop windows.", permission_level=PermissionLevel.L1, tags=["window", "desktop"]),
    ToolDefinition(id="clipboard_read_text", name="Clipboard Read Text", category="system", description="Read current plain text from Windows clipboard.", permission_level=PermissionLevel.L0, tags=["clipboard", "text"]),
    ToolDefinition(id="clipboard_write_text", name="Clipboard Write Text", category="system", description="Copy text into Windows system clipboard.", permission_level=PermissionLevel.L1, tags=["clipboard", "copy"]),
    ToolDefinition(id="clipboard_clear", name="Clipboard Clear", category="system", description="Clear sensitive contents from clipboard.", permission_level=PermissionLevel.L1, tags=["clipboard", "security"]),
    ToolDefinition(id="process_list_top", name="Process Manager (Top CPU/RAM)", category="system", description="List top resource-consuming processes.", permission_level=PermissionLevel.L0, tags=["process", "cpu", "ram"]),
    ToolDefinition(id="process_kill_pid", name="Process Terminate (Kill PID)", category="system", description="Terminate a misbehaving or hung process.", permission_level=PermissionLevel.L2, risk_level="high", tags=["process", "kill"]),
    ToolDefinition(id="cpu_ram_stats", name="CPU & RAM Load Inspector", category="system", description="Get overall system CPU load % and RAM usage.", permission_level=PermissionLevel.L0, tags=["hardware", "performance"]),
    ToolDefinition(id="disk_space_usage", name="Disk Space Analyzer", category="system", description="Check free/used storage across C: and local drives.", permission_level=PermissionLevel.L0, tags=["storage", "disk"]),
    ToolDefinition(id="app_launch_name", name="Application Launcher", category="system", description="Launch an installed Windows app by name (e.g. Chrome, VSCode, Notepad).", permission_level=PermissionLevel.L1, tags=["launcher", "apps"]),
    ToolDefinition(id="app_close_graceful", name="Application Close (Graceful)", category="system", description="Send WM_CLOSE signal to close app safely.", permission_level=PermissionLevel.L1, tags=["apps", "close"]),
    ToolDefinition(id="default_browser_check", name="Default Web Browser Detector", category="system", description="Detect current default web browser in Windows.", permission_level=PermissionLevel.L0, tags=["browser", "system"]),
    ToolDefinition(id="wifi_networks_scan", name="Wi-Fi Network Scanner", category="system", description="Scan available Wi-Fi SSIDs and signal strengths.", permission_level=PermissionLevel.L0, tags=["wifi", "network"]),
    ToolDefinition(id="bluetooth_devices_list", name="Bluetooth Devices Status", category="system", description="List paired and connected Bluetooth peripherals.", permission_level=PermissionLevel.L0, tags=["bluetooth", "devices"]),
    ToolDefinition(id="toast_notification_send", name="Native Toast Notifier", category="system", description="Display Windows native desktop notification toast.", permission_level=PermissionLevel.L0, tags=["notification", "toast"]),
    ToolDefinition(id="hotkey_trigger_keys", name="Keyboard Hotkey Dispatcher", category="system", description="Simulate key combinations (e.g. Ctrl+C, Alt+Tab, Win+D).", permission_level=PermissionLevel.L1, tags=["keyboard", "input"]),
    ToolDefinition(id="mouse_click_coord", name="Mouse Click Simulator", category="system", description="Click mouse at specified screen coordinates (x, y).", permission_level=PermissionLevel.L1, tags=["mouse", "input"]),
    ToolDefinition(id="mouse_scroll_wheel", name="Mouse Scroll Simulator", category="system", description="Scroll mouse wheel up or down by delta.", permission_level=PermissionLevel.L1, tags=["mouse", "scroll"]),
    ToolDefinition(id="file_search_everything", name="Instant File Search (Everything)", category="system", description="Search files and directories instantly by filename pattern.", permission_level=PermissionLevel.L0, tags=["files", "search"]),
    ToolDefinition(id="file_tree_walk", name="Directory Tree Builder", category="system", description="Generate formatted tree representation of folder.", permission_level=PermissionLevel.L0, tags=["files", "tree"]),
    ToolDefinition(id="file_hash_sha256", name="File Hash Checksum (SHA-256)", category="system", description="Calculate SHA-256 checksum of a local file.", permission_level=PermissionLevel.L0, tags=["files", "hash"]),
    ToolDefinition(id="temp_cleanup_scratch", name="Temp File Cleaner", category="system", description="Clean expired temp artifacts and cache files.", permission_level=PermissionLevel.L1, tags=["cleanup", "disk"]),
    ToolDefinition(id="screen_brightness", name="Display Brightness Adjuster", category="system", description="Get or set monitor brightness percentage.", permission_level=PermissionLevel.L1, tags=["display", "brightness"]),
    ToolDefinition(id="uptime_system_check", name="System Uptime Checker", category="system", description="Get duration since last Windows boot.", permission_level=PermissionLevel.L0, tags=["system", "uptime"]),
    ToolDefinition(id="reboot_confirm_schedule", name="System Reboot / Shutdown Scheduler", category="system", description="Schedule safe system restart after user confirmation.", permission_level=PermissionLevel.L2, risk_level="critical", tags=["power", "reboot"]),
    ToolDefinition(id="env_var_get", name="Environment Variable Reader", category="system", description="Read specific OS environment variable.", permission_level=PermissionLevel.L0, tags=["env", "config"]),
    ToolDefinition(id="sound_beep_alert", name="System Alert Tone", category="system", description="Play acoustic feedback chime upon task completion.", permission_level=PermissionLevel.L0, tags=["audio", "chime"]),
    ToolDefinition(id="active_user_whoami", name="Active User Inspector", category="system", description="Get current Windows username and domain context.", permission_level=PermissionLevel.L0, tags=["user", "auth"]),
]

# ---------------------------------------------------------------------------
# DOMAIN 7: Business, CRM, Marketing & Sales (35 Tools)
# ---------------------------------------------------------------------------
BUSINESS_TOOLS = [
    ToolDefinition(id="b2b_lead_research", name="B2B Lead Researcher", category="business", description="Discover prospective businesses matching ideal customer profile.", permission_level=PermissionLevel.L0, tags=["leads", "b2b", "sales"]),
    ToolDefinition(id="company_enrich_domain", name="Company Domain Enricher", category="business", description="Fetch industry, tech stack, and company size from domain.", permission_level=PermissionLevel.L0, tags=["enrichment", "b2b"]),
    ToolDefinition(id="hunter_email_finder", name="Hunter Email Finder & Verifier", category="business", description="Find professional email patterns for domain with deliverability score.", permission_level=PermissionLevel.L0, tags=["email", "hunter"]),
    ToolDefinition(id="crm_lead_create", name="CRM Create Lead", category="business", description="Record new prospect lead into CRM database.", permission_level=PermissionLevel.L1, tags=["crm", "leads"]),
    ToolDefinition(id="crm_lead_update_stage", name="CRM Update Pipeline Stage", category="business", description="Move deal to Qualified, Proposal, or Won stage.", permission_level=PermissionLevel.L1, tags=["crm", "pipeline"]),
    ToolDefinition(id="crm_contact_lookup", name="CRM Contact Search", category="business", description="Search contact history, notes, and past interactions.", permission_level=PermissionLevel.L0, tags=["crm", "contacts"]),
    ToolDefinition(id="outreach_email_generator", name="Cold Outreach Generator", category="business", description="Draft personalized high-converting cold email tailored to prospect.", permission_level=PermissionLevel.L0, tags=["sales", "outreach"]),
    ToolDefinition(id="followup_scheduler", name="Follow-Up Cadence Scheduler", category="business", description="Schedule day 3 / day 7 follow-up reminder sequence.", permission_level=PermissionLevel.L1, tags=["sales", "cadence"]),
    ToolDefinition(id="proposal_pdf_create", name="Client Proposal PDF Builder", category="business", description="Generate branded client proposal document with deliverables.", permission_level=PermissionLevel.L1, tags=["proposal", "sales"]),
    ToolDefinition(id="invoice_generator_pdf", name="Invoice PDF Generator", category="business", description="Generate itemized tax invoice PDF with GST/VAT calculations.", permission_level=PermissionLevel.L1, tags=["invoice", "billing"]),
    ToolDefinition(id="stripe_payment_link", name="Stripe Payment Link Creator", category="business", description="Create checkout payment link with price and currency.", permission_level=PermissionLevel.L2, tags=["stripe", "payments"]),
    ToolDefinition(id="stripe_customer_lookup", name="Stripe Customer Lookup", category="business", description="Get subscription status and transaction history from Stripe.", permission_level=PermissionLevel.L0, tags=["stripe", "billing"]),
    ToolDefinition(id="gst_tax_calculator", name="GST / Tax Calculator", category="business", description="Calculate CGST, SGST, IGST or sales tax breakdowns.", permission_level=PermissionLevel.L0, tags=["tax", "accounting"]),
    ToolDefinition(id="pl_summary_report", name="Profit & Loss Report Generator", category="business", description="Summarize income, expenses, and net margin over period.", permission_level=PermissionLevel.L0, tags=["finance", "pl"]),
    ToolDefinition(id="cac_ltv_calculator", name="CAC / LTV Unit Economics", category="business", description="Calculate Customer Acquisition Cost and Lifetime Value ratio.", permission_level=PermissionLevel.L0, tags=["marketing", "metrics"]),
    ToolDefinition(id="hubspot_contact_create", name="HubSpot Create Contact", category="business", description="Create or update contact in HubSpot CRM.", permission_level=PermissionLevel.L2, tags=["hubspot", "crm"]),
    ToolDefinition(id="salesforce_lead_create", name="Salesforce Create Lead", category="business", description="Insert lead record into Salesforce CRM.", permission_level=PermissionLevel.L2, tags=["salesforce", "crm"]),
    ToolDefinition(id="seo_keyword_research", name="SEO Keyword Research", category="business", description="Analyze search volume, keyword difficulty, and search intent.", permission_level=PermissionLevel.L0, tags=["seo", "keywords"]),
    ToolDefinition(id="seo_backlink_check", name="SEO Backlink Checker", category="business", description="Inspect referring domains and domain authority.", permission_level=PermissionLevel.L0, tags=["seo", "backlinks"]),
    ToolDefinition(id="seo_onpage_auditor", name="SEO On-Page Auditor", category="business", description="Audit H1/H2 tags, meta descriptions, image alt tags, and Core Web Vitals.", permission_level=PermissionLevel.L0, tags=["seo", "audit"]),
    ToolDefinition(id="competitor_price_tracker", name="Competitor Price Scraper", category="business", description="Monitor product pricing across competitor landing pages.", permission_level=PermissionLevel.L0, tags=["pricing", "competitors"]),
    ToolDefinition(id="social_sentiment_analyzer", name="Brand Sentiment Analyzer", category="business", description="Classify public sentiment across brand mentions (positive/neutral/negative).", permission_level=PermissionLevel.L0, tags=["sentiment", "brand"]),
    ToolDefinition(id="client_onboarding_checklist", name="Client Onboarding Checklist", category="business", description="Generate structured onboarding checklist for new client kickoff.", permission_level=PermissionLevel.L1, tags=["onboarding", "clients"]),
    ToolDefinition(id="booking_appointment_slot", name="Booking Reservation Engine", category="business", description="Find available meeting slots across calendar availability.", permission_level=PermissionLevel.L0, tags=["booking", "calendar"]),
    ToolDefinition(id="paper_trade_setup", name="Paper Trading Simulator", category="business", description="Simulate equity/crypto trade setup without real capital exposure.", permission_level=PermissionLevel.L1, tags=["trading", "paper_trading"]),
    ToolDefinition(id="portfolio_risk_analyzer", name="Portfolio Risk & Beta Calculator", category="business", description="Calculate Sharpe ratio, max drawdown, and beta of portfolio.", permission_level=PermissionLevel.L0, tags=["trading", "risk"]),
    ToolDefinition(id="nda_contract_template", name="NDA Contract Generator", category="business", description="Generate standard non-disclosure agreement document.", permission_level=PermissionLevel.L1, tags=["legal", "contracts"]),
    ToolDefinition(id="saas_mrr_churn_calc", name="SaaS MRR & Churn Calculator", category="business", description="Compute Monthly Recurring Revenue, Net Retention, and churn rate.", permission_level=PermissionLevel.L0, tags=["saas", "metrics"]),
    ToolDefinition(id="ad_copy_ab_generator", name="Ad Copy A/B Variant Generator", category="business", description="Generate 5 high-converting headlines and copy variants.", permission_level=PermissionLevel.L0, tags=["copywriting", "ads"]),
    ToolDefinition(id="client_deliverable_verifier", name="Client Deliverable QA Verifier", category="business", description="Verify contract requirements against completed work files.", permission_level=PermissionLevel.L0, tags=["qa", "deliverables"]),
    ToolDefinition(id="review_request_sender", name="Review & Testimonial Requester", category="business", description="Draft customer testimonial or Google review request.", permission_level=PermissionLevel.L1, tags=["reviews", "reputation"]),
    ToolDefinition(id="business_plan_outline", name="Business Model Canvas Builder", category="business", description="Generate structured 9-box Business Model Canvas outline.", permission_level=PermissionLevel.L0, tags=["strategy", "canvas"]),
    ToolDefinition(id="roi_calculator", name="ROI & Payback Calculator", category="business", description="Compute return on investment and payback period months.", permission_level=PermissionLevel.L0, tags=["finance", "roi"]),
    ToolDefinition(id="pitch_deck_outline", name="Pitch Deck Slide Blueprint", category="business", description="Generate 10-slide venture investor pitch deck structure.", permission_level=PermissionLevel.L0, tags=["pitch", "fundraising"]),
    ToolDefinition(id="competitor_swot_matrix", name="Competitor SWOT Matrix", category="business", description="Synthesize Strengths, Weaknesses, Opportunities, and Threats matrix.", permission_level=PermissionLevel.L0, tags=["strategy", "swot"]),
]

# ---------------------------------------------------------------------------
# DOMAIN 8: Data Science, AI & Analysis (30 Tools)
# ---------------------------------------------------------------------------
DATA_TOOLS = [
    ToolDefinition(id="pandas_df_summary", name="Pandas DataFrame Summary", category="data", description="Calculate summary statistics (mean, std, min, max, missing) of dataset.", permission_level=PermissionLevel.L0, tags=["pandas", "stats"]),
    ToolDefinition(id="pandas_df_filter", name="Pandas Query & Filter", category="data", description="Filter dataset rows matching SQL-like query expression.", permission_level=PermissionLevel.L0, tags=["pandas", "query"]),
    ToolDefinition(id="numpy_stats_calc", name="NumPy Vector Math Calculator", category="data", description="Compute vector dot products, matrix eigenvalues, and statistical distributions.", permission_level=PermissionLevel.L0, tags=["numpy", "math"]),
    ToolDefinition(id="matplotlib_chart_create", name="Matplotlib Plot Generator", category="data", description="Generate line, bar, scatter, or histogram chart PNG.", permission_level=PermissionLevel.L1, tags=["chart", "visualization"]),
    ToolDefinition(id="seaborn_heatmap_create", name="Seaborn Correlation Heatmap", category="data", description="Plot styled feature correlation heatmap matrix.", permission_level=PermissionLevel.L1, tags=["seaborn", "heatmap"]),
    ToolDefinition(id="outlier_detector_iqr", name="IQR Outlier Detector", category="data", description="Detect anomalous data points using Interquartile Range.", permission_level=PermissionLevel.L0, tags=["data_quality", "outliers"]),
    ToolDefinition(id="linear_regression_fit", name="Linear Regression Estimator", category="data", description="Fit trend line and compute R-squared slope and intercept.", permission_level=PermissionLevel.L0, tags=["ml", "regression"]),
    ToolDefinition(id="time_series_forecast", name="Time-Series Forecast (ARIMA)", category="data", description="Forecast next N intervals of metric using time-series modeling.", permission_level=PermissionLevel.L0, tags=["forecast", "time_series"]),
    ToolDefinition(id="vector_similarity_search", name="Vector Cosine Similarity Search", category="data", description="Find top-K nearest embedding vectors from database.", permission_level=PermissionLevel.L0, tags=["vector", "embeddings"]),
    ToolDefinition(id="text_cluster_kmeans", name="K-Means Text Clusterer", category="data", description="Cluster unstructured documents into K semantic topic groups.", permission_level=PermissionLevel.L0, tags=["ml", "clustering"]),
    ToolDefinition(id="json_schema_validate", name="JSON Schema Validator", category="data", description="Validate payload against strict Draft-7 JSON schema.", permission_level=PermissionLevel.L0, tags=["json", "validation"]),
    ToolDefinition(id="yaml_json_converter", name="YAML / JSON Bidirectional Converter", category="data", description="Convert YAML configuration to JSON format and vice versa.", permission_level=PermissionLevel.L0, tags=["yaml", "json"]),
    ToolDefinition(id="token_counter_tiktoken", name="LLM Token Counter", category="data", description="Count exact input/output tokens for Gemini, GPT-4, and Claude.", permission_level=PermissionLevel.L0, tags=["llm", "tokens"]),
    ToolDefinition(id="prompt_template_render", name="Prompt Template Renderer", category="data", description="Interpolate variables into Jinja2 / Mustache prompt templates.", permission_level=PermissionLevel.L0, tags=["prompt", "llm"]),
    ToolDefinition(id="model_eval_judge", name="LLM-as-a-Judge Scorer", category="data", description="Score model output accuracy, coherence, and instruction following (1-10).", permission_level=PermissionLevel.L0, tags=["eval", "judge"]),
    ToolDefinition(id="hallucination_verifier", name="Hallucination Fact Verifier", category="data", description="Verify every asserted claim in text against provided reference ground truth.", permission_level=PermissionLevel.L0, tags=["eval", "hallucination"]),
    ToolDefinition(id="text_embeddings_generate", name="Text Embeddings Generator", category="data", description="Generate 768/1536-dim vector embedding from text snippet.", permission_level=PermissionLevel.L0, tags=["embeddings", "vector"]),
    ToolDefinition(id="sentiment_classifier_nlp", name="Sentiment & Emotion Classifier", category="data", description="Classify text sentiment (Positive, Negative, Neutral, Angry, Joyful).", permission_level=PermissionLevel.L0, tags=["nlp", "sentiment"]),
    ToolDefinition(id="entity_recognizer_ner", name="Named Entity Recognizer (NER)", category="data", description="Extract Person, Organization, Location, Date entities from text.", permission_level=PermissionLevel.L0, tags=["ner", "entities"]),
    ToolDefinition(id="keyphrase_extractor", name="Keyphrase & Tag Extractor", category="data", description="Extract top keywords and semantic tags from document.", permission_level=PermissionLevel.L0, tags=["nlp", "keywords"]),
    ToolDefinition(id="data_anonymizer_pii", name="PII Mask & Anonymizer", category="data", description="Mask names, emails, phone numbers, and SSNs in dataset.", permission_level=PermissionLevel.L1, tags=["privacy", "pii"]),
    ToolDefinition(id="missing_data_imputer", name="Missing Data Imputer", category="data", description="Fill null/NaN values using mean, median, or forward fill.", permission_level=PermissionLevel.L1, tags=["data_prep", "pandas"]),
    ToolDefinition(id="one_hot_encoder", name="Categorical One-Hot Encoder", category="data", description="Encode string categories into binary indicator columns.", permission_level=PermissionLevel.L0, tags=["ml", "encoding"]),
    ToolDefinition(id="confusion_matrix_calc", name="Classification Confusion Matrix", category="data", description="Compute Precision, Recall, F1-Score, and Accuracy.", permission_level=PermissionLevel.L0, tags=["ml", "metrics"]),
    ToolDefinition(id="roc_auc_curve_plot", name="ROC-AUC Curve Plotter", category="data", description="Plot Receiver Operating Characteristic curve and calculate AUC score.", permission_level=PermissionLevel.L0, tags=["ml", "evaluation"]),
    ToolDefinition(id="ab_test_significance", name="A/B Test Statistical Significance", category="data", description="Calculate p-value and confidence interval from conversion rates.", permission_level=PermissionLevel.L0, tags=["stats", "ab_testing"]),
    ToolDefinition(id="pca_dimensionality_reduce", name="PCA Dimensionality Reducer", category="data", description="Reduce high-dimensional dataset to 2D/3D principal components.", permission_level=PermissionLevel.L0, tags=["ml", "pca"]),
    ToolDefinition(id="text_levenshtein_distance", name="Levenshtein String Distance", category="data", description="Calculate edit distance and fuzzy string match ratio.", permission_level=PermissionLevel.L0, tags=["nlp", "fuzzy"]),
    ToolDefinition(id="xml_to_dict_parser", name="XML to Dictionary Parser", category="data", description="Parse XML documents into nested Python dictionary structures.", permission_level=PermissionLevel.L0, tags=["xml", "parser"]),
    ToolDefinition(id="dataset_profile_report", name="Automated Dataset Profiler", category="data", description="Generate full profiling report with distributions and column types.", permission_level=PermissionLevel.L0, tags=["eda", "profiling"]),
]

# ---------------------------------------------------------------------------
# DOMAIN 9: Security, Privacy & Compliance (25 Tools)
# ---------------------------------------------------------------------------
SECURITY_TOOLS = [
    ToolDefinition(id="secret_scanner_regex", name="Secret & API Key Scanner", category="security", description="Scan codebase and files for leaked API keys, tokens, and private keys.", permission_level=PermissionLevel.L0, tags=["security", "secrets"]),
    ToolDefinition(id="dpapi_encrypt_secret", name="Windows DPAPI Encryptor", category="security", description="Encrypt sensitive token with hardware/OS-bound DPAPI key.", permission_level=PermissionLevel.L1, tags=["crypto", "dpapi"]),
    ToolDefinition(id="dpapi_decrypt_secret", name="Windows DPAPI Decryptor", category="security", description="Decrypt DPAPI-protected secret into memory.", permission_level=PermissionLevel.L1, tags=["crypto", "dpapi"]),
    ToolDefinition(id="password_entropy_calc", name="Password Strength & Entropy", category="security", description="Evaluate bits of entropy and dictionary vulnerabilities in password.", permission_level=PermissionLevel.L0, tags=["auth", "password"]),
    ToolDefinition(id="token_mask_redactor", name="Sensitive Data Redactor", category="security", description="Mask credit card numbers, secrets, and auth tokens in text logs.", permission_level=PermissionLevel.L0, tags=["privacy", "redaction"]),
    ToolDefinition(id="url_safety_checker", name="Malicious URL & Phishing Checker", category="security", description="Scan URL against Google Safe Browsing / VirusTotal database.", permission_level=PermissionLevel.L0, tags=["security", "url"]),
    ToolDefinition(id="jwt_token_inspector", name="JWT Token Inspector", category="security", description="Decode and inspect header, payload claims, and expiration timestamp.", permission_level=PermissionLevel.L0, tags=["auth", "jwt"]),
    ToolDefinition(id="ip_geo_lookup", name="IP Geolocation & ASN Lookup", category="security", description="Identify country, city, ISP, and VPN/Proxy status of IP address.", permission_level=PermissionLevel.L0, tags=["network", "ip"]),
    ToolDefinition(id="file_permission_audit", name="File ACL Permission Auditor", category="security", description="Audit read/write permissions and owner of sensitive directories.", permission_level=PermissionLevel.L0, tags=["security", "acl"]),
    ToolDefinition(id="network_connections_list", name="Active Network Connections (netstat)", category="security", description="List established TCP/UDP sockets and remote IPs.", permission_level=PermissionLevel.L0, tags=["network", "netstat"]),
    ToolDefinition(id="sha512_hash_calc", name="SHA-512 Hash Generator", category="security", description="Compute SHA-512 cryptographic hash of text or file.", permission_level=PermissionLevel.L0, tags=["crypto", "hash"]),
    ToolDefinition(id="cors_header_inspector", name="CORS Configuration Auditor", category="security", description="Verify Access-Control-Allow-Origin headers on API endpoint.", permission_level=PermissionLevel.L0, tags=["web", "cors"]),
    ToolDefinition(id="sql_injection_detector", name="SQL Injection Pattern Scanner", category="security", description="Identify unsafe unparameterized string concatenations in SQL queries.", permission_level=PermissionLevel.L0, tags=["security", "sqli"]),
    ToolDefinition(id="xss_payload_sanitizer", name="XSS HTML Sanitizer", category="security", description="Strip dangerous script tags and event handlers from HTML string.", permission_level=PermissionLevel.L0, tags=["security", "xss"]),
    ToolDefinition(id="csrf_token_verifier", name="CSRF Token Guard", category="security", description="Verify Anti-CSRF token match in incoming web requests.", permission_level=PermissionLevel.L0, tags=["security", "csrf"]),
    ToolDefinition(id="rate_limit_token_bucket", name="Token Bucket Rate Limiter", category="security", description="Enforce sliding-window rate limit per IP or client token.", permission_level=PermissionLevel.L0, tags=["security", "rate_limit"]),
    ToolDefinition(id="audit_log_record", name="Security Audit Log Recorder", category="security", description="Write tamper-evident record of user action to audit log.", permission_level=PermissionLevel.L1, tags=["audit", "compliance"]),
    ToolDefinition(id="session_token_generate", name="Secure Random Token Generator", category="security", description="Generate cryptographically secure 256-bit entropy token.", permission_level=PermissionLevel.L0, tags=["crypto", "tokens"]),
    ToolDefinition(id="totp_mfa_verify", name="TOTP Multi-Factor Authenticator", category="security", description="Verify 6-digit Google Authenticator / TOTP time-based code.", permission_level=PermissionLevel.L1, tags=["mfa", "auth"]),
    ToolDefinition(id="sandbox_container_isolate", name="Sandbox Code Isolation Guard", category="security", description="Validate execution boundary before running untrusted scripts.", permission_level=PermissionLevel.L1, tags=["sandbox", "isolation"]),
    ToolDefinition(id="gdpr_data_export", name="GDPR User Data Exporter", category="security", description="Export all user records in machine-readable JSON archive.", permission_level=PermissionLevel.L1, tags=["gdpr", "compliance"]),
    ToolDefinition(id="gdpr_erasure_tombstone", name="GDPR Right-to-be-Forgotten Tombstone", category="security", description="Anonymize user records while preserving cryptographic integrity.", permission_level=PermissionLevel.L2, risk_level="high", tags=["gdpr", "compliance"]),
    ToolDefinition(id="subresource_integrity_hash", name="Subresource Integrity (SRI) Hash", category="security", description="Generate sha384 SRI integrity tag for CDN script inclusion.", permission_level=PermissionLevel.L0, tags=["web", "sri"]),
    ToolDefinition(id="security_headers_scan", name="HTTP Security Headers Scanner", category="security", description="Check HSTS, Content-Security-Policy, and X-Frame-Options.", permission_level=PermissionLevel.L0, tags=["security", "headers"]),
    ToolDefinition(id="prompt_injection_guard", name="Prompt Injection & Jailbreak Guard", category="security", description="Detect instruction hijacking and adversarial jailbreak patterns.", permission_level=PermissionLevel.L0, tags=["ai_security", "prompt_guard"]),
]

# ---------------------------------------------------------------------------
# DOMAIN 10: Automation, MCP & Workflows (25 Tools)
# ---------------------------------------------------------------------------
AUTOMATION_TOOLS = [
    ToolDefinition(id="n8n_trigger_webhook", name="n8n Workflow Webhook Trigger", category="automation", description="Dispatch payload to an active n8n automation workflow.", permission_level=PermissionLevel.L2, tags=["n8n", "webhook", "automation"]),
    ToolDefinition(id="n8n_list_workflows", name="n8n List Active Workflows", category="automation", description="Fetch list of configured and running n8n automation nodes.", permission_level=PermissionLevel.L0, tags=["n8n", "workflows"]),
    ToolDefinition(id="zapier_webhook_dispatch", name="Zapier Webhook Dispatcher", category="automation", description="Trigger Zapier Zap via incoming webhook URL.", permission_level=PermissionLevel.L2, tags=["zapier", "automation"]),
    ToolDefinition(id="make_integromat_trigger", name="Make (Integromat) Webhook Trigger", category="automation", description="Send event payload to Make.com scenario webhook.", permission_level=PermissionLevel.L2, tags=["make", "automation"]),
    ToolDefinition(id="cron_schedule_task", name="Cron Task Scheduler", category="automation", description="Schedule recurring task with standard 5-part cron syntax.", permission_level=PermissionLevel.L1, tags=["cron", "schedule"]),
    ToolDefinition(id="cron_list_jobs", name="Cron List Scheduled Jobs", category="automation", description="List active scheduled timers and recurring background jobs.", permission_level=PermissionLevel.L0, tags=["cron", "jobs"]),
    ToolDefinition(id="eventbus_publish_event", name="EventBus Event Publisher", category="automation", description="Broadcast typed event across VYOM runtime subscribers.", permission_level=PermissionLevel.L1, tags=["eventbus", "events"]),
    ToolDefinition(id="eventbus_subscribe_topic", name="EventBus Topic Listener", category="automation", description="Register callback handler for specific event topic.", permission_level=PermissionLevel.L1, tags=["eventbus", "subscribe"]),
    ToolDefinition(id="mcp_server_connect", name="MCP Server Connector", category="automation", description="Connect to an external Model Context Protocol server via stdio/SSE.", permission_level=PermissionLevel.L2, tags=["mcp", "connector"]),
    ToolDefinition(id="mcp_server_list_tools", name="MCP Server List Tools", category="automation", description="Discover all tool schemas exposed by connected MCP server.", permission_level=PermissionLevel.L0, tags=["mcp", "discovery"]),
    ToolDefinition(id="mcp_tool_execute", name="MCP Tool Proxy Invoker", category="automation", description="Execute tool on a remote MCP server with JSON arguments.", permission_level=PermissionLevel.L2, tags=["mcp", "invoke"]),
    ToolDefinition(id="subagent_task_delegate", name="Subagent Task Delegator", category="automation", description="Spawn specialized subagent for background execution.", permission_level=PermissionLevel.L1, tags=["agents", "subagent"]),
    ToolDefinition(id="kanban_task_dispatch", name="Kanban Task Dispatcher", category="automation", description="Move task card to In-Progress and assign role agent.", permission_level=PermissionLevel.L1, tags=["kanban", "tasks"]),
    ToolDefinition(id="retry_exponential_backoff", name="Exponential Backoff Retry Engine", category="automation", description="Execute function with jitter and exponential backoff retry.", permission_level=PermissionLevel.L1, tags=["resilience", "retry"]),
    ToolDefinition(id="circuit_breaker_guard", name="Circuit Breaker Status Guard", category="automation", description="Inspect and manage closed/open/half-open circuit breakers.", permission_level=PermissionLevel.L0, tags=["resilience", "circuit_breaker"]),
    ToolDefinition(id="webhook_receiver_listen", name="Inbound Webhook Listener", category="automation", description="Listen for incoming HTTP webhook payloads on local port.", permission_level=PermissionLevel.L1, tags=["webhook", "receiver"]),
    ToolDefinition(id="batch_task_parallel_run", name="Parallel Batch Task Runner", category="automation", description="Run list of independent tasks concurrently with semaphore limit.", permission_level=PermissionLevel.L1, tags=["batch", "concurrency"]),
    ToolDefinition(id="step_evidence_verifier", name="Step Execution Evidence Verifier", category="automation", description="Verify that output artifacts exist and meet quality criteria.", permission_level=PermissionLevel.L0, tags=["verification", "qa"]),
    ToolDefinition(id="macro_sequence_runner", name="Macro Action Sequence Runner", category="automation", description="Execute multi-step predefined macro workflow in order.", permission_level=PermissionLevel.L2, tags=["macro", "workflow"]),
    ToolDefinition(id="smart_notification_router", name="Smart Notification Router", category="automation", description="Route critical alerts to Desktop Toast, Telegram, or Discord.", permission_level=PermissionLevel.L1, tags=["alerts", "notifications"]),
    ToolDefinition(id="data_pipeline_transform", name="Data Pipeline Step Transformer", category="automation", description="Pipe output from Tool A into transformation step for Tool B.", permission_level=PermissionLevel.L1, tags=["pipeline", "etl"]),
    ToolDefinition(id="state_checkpoint_save", name="Execution State Checkpoint", category="automation", description="Save durable checkpoint to recover state in case of crash.", permission_level=PermissionLevel.L1, tags=["persistence", "recovery"]),
    ToolDefinition(id="heartbeat_health_monitor", name="Heartbeat Health Monitor", category="automation", description="Check health and ping of all active background workers.", permission_level=PermissionLevel.L0, tags=["health", "monitor"]),
    ToolDefinition(id="dependency_graph_resolver", name="Task Dependency Graph Resolver", category="automation", description="Resolve topological execution order across DAG tasks.", permission_level=PermissionLevel.L0, tags=["dag", "orchestration"]),
    ToolDefinition(id="auto_rollback_on_failure", name="Automated Rollback Engine", category="automation", description="Revert database and file modifications if step fails.", permission_level=PermissionLevel.L2, tags=["rollback", "safety"]),
]

# ---------------------------------------------------------------------------
# Complete Catalog Export (Combined 335+ Tools)
# ---------------------------------------------------------------------------
ALL_300_TOOLS: list[ToolDefinition] = (
    DEV_TOOLS
    + PRODUCTIVITY_TOOLS
    + COMMUNICATION_TOOLS
    + RESEARCH_TOOLS
    + MEDIA_TOOLS
    + SYSTEM_TOOLS
    + BUSINESS_TOOLS
    + DATA_TOOLS
    + SECURITY_TOOLS
    + AUTOMATION_TOOLS
)


def get_all_tool_definitions() -> list[ToolDefinition]:
    """Returns the entire 335+ tool definition list."""
    return ALL_300_TOOLS


def get_tools_by_category(category: str) -> list[ToolDefinition]:
    """Filter tools by category."""
    return [t for t in ALL_300_TOOLS if t.category.lower() == category.lower()]


def count_tools() -> dict[str, int]:
    """Return count breakdown across all categories."""
    counts: dict[str, int] = {}
    for t in ALL_300_TOOLS:
        counts[t.category] = counts.get(t.category, 0) + 1
    counts["total"] = len(ALL_300_TOOLS)
    return counts


def search_tools(query: str, limit: int = 8) -> list[ToolDefinition]:
    """Fast lexical and tag search across the 335+ tool catalog."""
    query_terms = [t.lower() for t in query.split()]
    scores: list[tuple[int, ToolDefinition]] = []
    for tool in ALL_300_TOOLS:
        score = 0
        text = f"{tool.id} {tool.name} {tool.description} {' '.join(tool.tags)}".lower()
        for term in query_terms:
            if term in tool.id:
                score += 10
            elif term in tool.name.lower():
                score += 6
            elif any(term in tag for tag in tool.tags):
                score += 4
            elif term in text:
                score += 1
        if score > 0:
            scores.append((score, tool))
    scores.sort(key=lambda x: x[0], reverse=True)
    return [t[1] for t in scores[:limit]]

