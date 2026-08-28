# VYOM Connectors, MCP, Plugins & Automation Guide

This guide documents the architecture, SDK, and operational procedures for extending Vyom with **Connectors**, **Model Context Protocol (MCP) Servers**, **Third-Party Plugins**, and **Multi-Step Autonomous Workflows**.

---

## 1. Core Architecture Overview

```
                      VYOM
                        │
              ┌─────────▼─────────┐
              │    AI AGENT       │
              │ Planner / Reasoner│
              └─────────┬─────────┘
                        │
                 Relevant Tool Search
                        │
              ┌─────────▼─────────┐
              │   TOOL REGISTRY   │
              └──────┬──┬──┬─────┘
                     │  │  │
             ┌───────┘  │  └────────┐
             ▼          ▼           ▼
           MCP       Plugins      Native
         Servers    Connectors     Tools
             │          │
       ┌─────┼─────┐    ├───────────────┐
       ▼     ▼     ▼    ▼       ▼       ▼
    GitHub Slack Custom Gmail  Drive Calendar
       MCP   MCP   MCP   OAuth OAuth OAuth

                        │
                ┌───────▼────────┐
                │ Permission Gate│
                └───────┬────────┘
                        │
            ┌───────────▼────────────┐
            │ Human Approval if risky│
            └───────────┬────────────┘
                        │
                    Execution
                        │
                ┌───────▼───────┐
                │ Audit / Runs  │
                └───────────────┘
```

---

## 2. Creating a Custom Connector via Plugin SDK

You can define a new connector in seconds using the declarative `define_connector` helper:

```python
from app.connectors.base import ConnectorCategory, ConnectorAuthType
from app.connectors.plugin_sdk import define_connector

async def execute_stripe_tool(tool_name: str, arguments: dict, context):
    if tool_name == "create_payment_link":
        # Call Stripe API
        return {"payment_url": f"https://buy.stripe.com/test_{arguments['amount']}"}
    raise NotImplementedError(tool_name)

stripe_connector = define_connector(
    id="stripe",
    name="Stripe Payments",
    description="Create payment links, inspect invoices, and track subscriptions.",
    category=ConnectorCategory.CRM,
    auth_type=ConnectorAuthType.API_KEY,
    tools=[
        {
            "name": "create_payment_link",
            "description": "Generate a checkout link for an invoice",
            "input_schema": {
                "type": "object",
                "properties": {
                    "amount": {"type": "number", "description": "Amount in USD"},
                    "description": {"type": "string"},
                },
                "required": ["amount"],
            },
            "risk_level": "medium",
        }
    ],
    execute_fn=execute_stripe_tool,
)
```

---

## 3. Model Context Protocol (MCP) Integration

Vyom connects to standard MCP servers over `stdio`, `http`, or `sse`.

### Adding via UI
1. Click **Connectors & MCP** in Vyom's topbar / dock.
2. Switch to the **MCP Servers** tab or click **Add Custom MCP**.
3. Fill in:
   - **ID**: `github-mcp`
   - **Display Name**: `GitHub MCP Server`
   - **Transport**: `stdio`
   - **Command**: `npx`
   - **Args**: `-y @modelcontextprotocol/server-github`
4. Click **Test Connection** to preview dynamically discovered tools.
5. Click **Save & Register Server**.

### Adding via REST API
```bash
POST /api/mcp/servers
Content-Type: application/json

{
  "id": "filesystem-mcp",
  "name": "Local Filesystem MCP",
  "transport": "stdio",
  "command": "npx",
  "args": ["-y", "@modelcontextprotocol/server-filesystem", "C:/Projects"]
}
```

---

## 4. Multi-Step Workflows & Automations

### Natural Language Synthesis
In the Automations tab, input any plain English or Hinglish instruction:
> *"Every weekday at 9 AM check my GitHub issues, summarize high priority ones and prepare an email digest."*

Vyom converts this into a structured pipeline:
```
WHEN (Schedule: 0 9 * * 1-5)
  ↓
TOOL (github.search_issues)
  ↓
AI STEP (Summarize & Triage)
  ↓
TOOL (gmail.create_draft)
```

---

## 5. Security & Least Privilege

- **Credential Protection**: All API keys and OAuth tokens are stored in the OS-backed DPAPI / AES encrypted vault (`app/integrations/secrets.py`).
- **Approval Gate**: High-risk actions (`risk_level: "high"`, such as sending external emails, deleting accounts, executing financial orders, merging PRs) automatically pause and request human authorization.
- **Untrusted Input Defense**: All tool outputs and MCP server responses are quarantined and sanitized to prevent prompt injection attacks.
