"""
VYOM Autonomous Corporate Hierarchy & Dynamic Team Builder
=========================================================
Operates VYOM as the Central CEO who autonomously creates, assigns, and manages:
- Department Managers (VP Level)
- Team Leaders (Campaign / Niche Managers)
- Autonomous Worker Agents (Execution Specialists)
- Dynamic Tool & Skill Synthesis (No manual coding required by user)
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence
from uuid import uuid4

from app.sheets.local_excel import get_local_excel_service

ORGANIZATION_STORAGE_PATH = Path("services/brain/data/company_hierarchy.json")
CUSTOM_AGENTS_STORAGE_DIR = Path("services/brain/data/custom_agents")


@dataclass
class EmployeeAgent:
    agent_id: str
    name: str
    tier: str  # 'VP_MANAGER', 'TEAM_LEAD', 'SPECIALIST_WORKER'
    department: str  # 'Social Media & Growth', 'Sales & CRM', 'Trading & Finance', 'Engineering & Desktop'
    role_description: str
    assigned_skills: list[str] = field(default_factory=list)
    active_tasks: list[str] = field(default_factory=list)
    created_dynamically: bool = False
    status: str = "Active"


@dataclass
class Department:
    name: str
    vp_manager_id: str
    team_leads: list[str] = field(default_factory=list)
    specialist_workers: list[str] = field(default_factory=list)
    responsibilities: list[str] = field(default_factory=list)


# Default Corporate Organization Structure for VYOM
DEFAULT_DEPARTMENTS = [
    Department(
        name="Social Media & Viral Growth",
        vp_manager_id="vp_social_growth",
        team_leads=["lead_instagram_content", "lead_youtube_media"],
        specialist_workers=["worker_hook_writer", "worker_script_dialogue", "worker_hashtag_matrix", "worker_calendar_planner"],
        responsibilities=["Client Instagram calendars", "Reel/Short dialogue scripts", "0-3s hook optimization", "Upload schedules"],
    ),
    Department(
        name="Sales, Lead Finder & CRM",
        vp_manager_id="vp_sales_growth",
        team_leads=["lead_b2b_prospecting"],
        specialist_workers=["worker_web_scraper", "worker_lead_qualifier", "worker_crm_logger", "worker_outreach_drafter"],
        responsibilities=["Industry lead scraping", "Contact verification", "CRM pipeline upsert", "Client delivery packages"],
    ),
    Department(
        name="Trading & Financial Intelligence",
        vp_manager_id="vp_chief_investment_officer",
        team_leads=["lead_alpha_trading"],
        specialist_workers=["worker_market_quote_streamer", "worker_risk_controller", "worker_paper_broker", "worker_catalyst_researcher"],
        responsibilities=["Real-time quotes", "Risk & kill-switch rules", "Paper order execution", "Daily market briefings"],
    ),
    Department(
        name="Engineering & Desktop Operations",
        vp_manager_id="vp_chief_technology_officer",
        team_leads=["lead_desktop_automation", "lead_browser_playwright"],
        specialist_workers=["worker_excel_generator", "worker_window_controller", "worker_screen_clicker", "worker_ad_skipper"],
        responsibilities=["Formatted Excel exports", "Playwright web scraping", "Screen clicking", "YouTube ad bypass"],
    ),
]


class CEOOrchestrationEngine:
    """Master CEO coordination engine for VYOM."""

    def __init__(self, storage_path: Path | None = None):
        self.storage_path = storage_path or ORGANIZATION_STORAGE_PATH
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        CUSTOM_AGENTS_STORAGE_DIR.mkdir(parents=True, exist_ok=True)
        self.departments: dict[str, Department] = {}
        self.employees: dict[str, EmployeeAgent] = {}
        self._load_or_bootstrap()

    def _load_or_bootstrap(self) -> None:
        if self.storage_path.exists():
            try:
                raw = json.loads(self.storage_path.read_text(encoding="utf-8"))
                for dept_data in raw.get("departments", []):
                    d = Department(**dept_data)
                    self.departments[d.name] = d
                for emp_data in raw.get("employees", []):
                    e = EmployeeAgent(**emp_data)
                    self.employees[e.agent_id] = e
                return
            except Exception:
                pass
        self._bootstrap_default_organization()

    def _bootstrap_default_organization(self) -> None:
        # Pre-seed default corporate roster
        initial_employees = [
            EmployeeAgent("vp_social_growth", "Maya / Director of Content", "VP_MANAGER", "Social Media & Viral Growth", "Oversees all client social media campaigns, niche isolation, and 30-day plans"),
            EmployeeAgent("lead_instagram_content", "Lead Instagram Strategist", "TEAM_LEAD", "Social Media & Viral Growth", "Manages Instagram content calendars and niche hooks"),
            EmployeeAgent("worker_grok_trend_hunter", "Grok Viral Trend Hunter", "SPECIALIST_WORKER", "Social Media & Viral Growth", "Scans breaking viral topics and contrarian hooks in real time"),
            EmployeeAgent("worker_prime_director", "Prime Video Director", "SPECIALIST_WORKER", "Social Media & Viral Growth", "Multi-modal director for retention curves, B-roll cues, and video pacing"),
            EmployeeAgent("worker_openclaw_scraper", "OpenClaw Competitor Scraper", "SPECIALIST_WORKER", "Social Media & Viral Growth", "Deconstructs high-performing competitor reels and formats"),
            EmployeeAgent("worker_hermes_engagement", "Hermes DM & Comment Nurturer", "SPECIALIST_WORKER", "Social Media & Viral Growth", "Automates keyword comment triggers, lead routing, and DMs"),
            EmployeeAgent("worker_carousel_architect", "Carousel 10-Slide Architect", "SPECIALIST_WORKER", "Social Media & Viral Growth", "Designs high-value 10-slide visual carousel content"),
            EmployeeAgent("worker_hook_writer", "Viral Hook Specialist", "SPECIALIST_WORKER", "Social Media & Viral Growth", "Writes high-retention 0-3s pattern interrupt hooks"),
            EmployeeAgent("worker_script_dialogue", "Dialogue Scriptwriter", "SPECIALIST_WORKER", "Social Media & Viral Growth", "Writes full visual and audio cues for short-form videos"),
            EmployeeAgent("worker_hashtag_matrix", "Hashtag & SEO Specialist", "SPECIALIST_WORKER", "Social Media & Viral Growth", "Generates high-conversion hashtags and captions"),
            EmployeeAgent("worker_calendar_planner", "Content Calendar Planner", "SPECIALIST_WORKER", "Social Media & Viral Growth", "Formats 30-day schedules and posts"),

            EmployeeAgent("vp_sales_growth", "VP of Client Growth", "VP_MANAGER", "Sales, Lead Finder & CRM", "Directs B2B pipeline, lead generation, and client outreach"),
            EmployeeAgent("lead_b2b_prospecting", "Lead Prospecting Manager", "TEAM_LEAD", "Sales, Lead Finder & CRM", "Oversees industry scraping and qualification scoring"),
            EmployeeAgent("worker_web_scraper", "Browser Lead Scraper", "SPECIALIST_WORKER", "Sales, Lead Finder & CRM", "Scrapes web targets and directories for companies"),
            EmployeeAgent("worker_lead_qualifier", "Lead Qualification Auditor", "SPECIALIST_WORKER", "Sales, Lead Finder & CRM", "Evaluates lead legitimacy and contact details"),
            EmployeeAgent("worker_crm_logger", "CRM Pipeline Logger", "SPECIALIST_WORKER", "Sales, Lead Finder & CRM", "Stores leads into persistent SQLite CRM database"),
            EmployeeAgent("worker_outreach_drafter", "Outreach Copywriter", "SPECIALIST_WORKER", "Sales, Lead Finder & CRM", "Prepares customized client proposal emails"),

            EmployeeAgent("vp_chief_investment_officer", "Chief Investment Officer", "VP_MANAGER", "Trading & Financial Intelligence", "Manages paper portfolio, market regimes, and risk protocols"),
            EmployeeAgent("lead_alpha_trading", "Alpha Trading Lead", "TEAM_LEAD", "Trading & Financial Intelligence", "Monitors trade setups, indicators, and setups"),
            EmployeeAgent("worker_market_quote_streamer", "Real-Time Quote Specialist", "SPECIALIST_WORKER", "Trading & Financial Intelligence", "Fetches live Yahoo Finance and crypto feeds"),
            EmployeeAgent("worker_risk_controller", "Risk & Kill-Switch Controller", "SPECIALIST_WORKER", "Trading & Financial Intelligence", "Enforces 2% max risk per trade and daily loss limits"),
            EmployeeAgent("worker_paper_broker", "Paper Execution Broker", "SPECIALIST_WORKER", "Trading & Financial Intelligence", "Simulates realistic order fills and slippage"),

            EmployeeAgent("vp_chief_technology_officer", "Chief Technology Officer", "VP_MANAGER", "Engineering & Desktop Operations", "Coordinates local system tools, browser agents, and automation"),
            EmployeeAgent("lead_desktop_automation", "Desktop Automation Lead", "TEAM_LEAD", "Engineering & Desktop Operations", "Controls Windows native window management and files"),
            EmployeeAgent("worker_excel_generator", "Excel & Spreadsheet Specialist", "SPECIALIST_WORKER", "Engineering & Desktop Operations", "Generates styled .xlsx and .csv files"),
            EmployeeAgent("worker_screen_clicker", "Screen Vision & Clicker Bot", "SPECIALIST_WORKER", "Engineering & Desktop Operations", "Probes display screen and executes coordinate clicks"),
            EmployeeAgent("worker_ad_skipper", "YouTube Ad Bypass Bot", "SPECIALIST_WORKER", "Engineering & Desktop Operations", "Detects and clicks YouTube skip ad buttons automatically"),
        ]

        for emp in initial_employees:
            self.employees[emp.agent_id] = emp
        for dept in DEFAULT_DEPARTMENTS:
            self.departments[dept.name] = dept
        self._save()

    def _save(self) -> None:
        try:
            dump = {
                "ceo": "VYOM Core / Operator",
                "owner": "Gunjan",
                "departments": [asdict(d) for d in self.departments.values()],
                "employees": [asdict(e) for e in self.employees.values()],
            }
            self.storage_path.write_text(json.dumps(dump, indent=2), encoding="utf-8")
        except Exception:
            pass

    def create_dynamic_agent(
        self,
        name: str,
        department_name: str,
        role_description: str,
        skills: list[str],
        tier: str = "SPECIALIST_WORKER",
    ) -> EmployeeAgent:
        """Dynamically synthesizes and hires a new AI worker on-demand."""
        agent_id = f"custom_agent_{uuid4().hex[:8]}"
        emp = EmployeeAgent(
            agent_id=agent_id,
            name=name,
            tier=tier,
            department=department_name,
            role_description=role_description,
            assigned_skills=skills,
            created_dynamically=True,
            status="Active",
        )
        self.employees[agent_id] = emp

        # Attach to department
        if department_name in self.departments:
            dept = self.departments[department_name]
            if tier == "TEAM_LEAD":
                dept.team_leads.append(agent_id)
            else:
                dept.specialist_workers.append(agent_id)

        # Save record
        self._save()
        
        # Write agent spec to custom agents dir
        agent_file = CUSTOM_AGENTS_STORAGE_DIR / f"{agent_id}.json"
        agent_file.write_text(json.dumps(asdict(emp), indent=2), encoding="utf-8")
        return emp

    def get_org_chart(self) -> dict[str, Any]:
        """Returns the full corporate tree representation."""
        chart: dict[str, Any] = {
            "CEO": "VYOM Core Operating Authority",
            "Boss / Owner": "Gunjan",
            "Total Employees": len(self.employees),
            "Departments": {},
        }
        for dname, dept in self.departments.items():
            vp = self.employees.get(dept.vp_manager_id)
            leads = [self.employees[lid].name for lid in dept.team_leads if lid in self.employees]
            workers = [self.employees[wid].name for wid in dept.specialist_workers if wid in self.employees]
            chart["Departments"][dname] = {
                "VP Manager": vp.name if vp else dept.vp_manager_id,
                "Team Leads": leads,
                "Specialist Workers": workers,
                "Key Responsibilities": dept.responsibilities,
            }
        return chart

    def execute_as_ceo(self, user_mission: str) -> dict[str, Any]:
        """CEO level task triage, delegation to appropriate Department Manager, and worker execution."""
        mission_lower = user_mission.lower()

        # Match appropriate department
        if any(k in mission_lower for k in ("instagram", "reel", "youtube", "content", "hook", "caption", "social")):
            dept = self.departments.get("Social Media & Viral Growth")
            assigned_vp = self.employees["vp_social_growth"]
            delegation_plan = [
                "1. VP Social Growth reviews niche rules and client constraints.",
                "2. Hook Specialist formulates 0-3s pattern interrupts.",
                "3. Scriptwriter drafts audio/visual cues and dialogue.",
                "4. Calendar Planner builds formatted 30-day Excel sheet.",
            ]
        elif any(k in mission_lower for k in ("lead", "scrape", "crm", "client", "prospect", "outreach")):
            dept = self.departments.get("Sales, Lead Finder & CRM")
            assigned_vp = self.employees["vp_sales_growth"]
            delegation_plan = [
                "1. VP Sales defines target industry query and criteria.",
                "2. Web Scraper extracts verified company details.",
                "3. CRM Logger saves leads to persistent SQLite database.",
            ]
        elif any(k in mission_lower for k in ("trading", "stock", "crypto", "market", "paper trade", "risk")):
            dept = self.departments.get("Trading & Financial Intelligence")
            assigned_vp = self.employees["vp_chief_investment_officer"]
            delegation_plan = [
                "1. CIO checks current market regime and risk boundaries.",
                "2. Quote Specialist streams live pricing.",
                "3. Paper Broker simulates order fill within 2% risk limits.",
            ]
        else:
            dept = self.departments.get("Engineering & Desktop Operations")
            assigned_vp = self.employees["vp_chief_technology_officer"]
            delegation_plan = [
                "1. CTO analyzes required system capabilities.",
                "2. Automated specialist executes browser/desktop action.",
                "3. Output verified on local filesystem.",
            ]

        return {
            "ceo_decision": f"Mission delegated to {assigned_vp.department}",
            "commanding_vp": assigned_vp.name,
            "delegation_plan": delegation_plan,
            "status": "Delegated & In Progress",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


_default_ceo: CEOOrchestrationEngine | None = None

def get_ceo_engine() -> CEOOrchestrationEngine:
    global _default_ceo
    if _default_ceo is None:
        _default_ceo = CEOOrchestrationEngine()
    return _default_ceo
