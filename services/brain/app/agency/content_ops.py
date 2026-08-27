"""
VYOM Agency & Multi-Account Content Operating System
====================================================
Provides strict workspace isolation for multiple clients and multiple social media accounts.
Handles:
- Client & Account Profiles (Niche, Tone, Schedule, Hashtag Pool, Guidelines)
- Viral Research & 0-3s Hook Formulas
- Reel / Short Video Dialogue & Script Production
- 30-Day Content Calendar Generation & Excel Export
- Document / Presentation / NotebookLM Research Synthesis
- Zero-Bleed Data Isolation between Clients
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from app.sheets.local_excel import get_local_excel_service

AGENCY_STORAGE_DIR = Path("services/brain/data/agency_workspaces")


@dataclass
class AccountProfile:
    account_id: str
    owner_name: str
    platform: str  # 'instagram', 'youtube', 'linkedin', 'twitter'
    handle: str
    niche: str
    target_audience: str
    tone: str
    upload_time: str  # e.g. "18:30 IST"
    posting_frequency: str  # e.g. "1 reel/day"
    preferred_hooks: list[str] = field(default_factory=list)
    hashtag_pool: list[str] = field(default_factory=list)
    cta_templates: list[str] = field(default_factory=list)
    brand_rules: list[str] = field(default_factory=list)


@dataclass
class ContentItem:
    day_number: int
    title: str
    niche: str
    content_format: str  # 'Reel', 'Carousel', 'Single Image', 'Short'
    hook_3s: str         # 0-3s pattern interrupt
    script_dialogue: str # Visual cues + Spoken dialogue
    cta: str             # Call to action
    caption: str         # High conversion caption
    hashtags: list[str]  # Targeted hashtag set
    scheduled_time: str  # Post time
    status: str = "Draft"


class ClientWorkspaceManager:
    """Manages isolated workspaces for multiple clients and separate brand accounts."""

    def __init__(self, base_dir: Path | None = None):
        self.base_dir = base_dir or AGENCY_STORAGE_DIR
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._accounts: dict[str, AccountProfile] = {}
        self._load()
        self._ensure_defaults()

    def _get_account_file(self, account_id: str) -> Path:
        return self.base_dir / f"{account_id}_profile.json"

    def _load(self) -> None:
        for file in self.base_dir.glob("*_profile.json"):
            try:
                data = json.loads(file.read_text(encoding="utf-8"))
                prof = AccountProfile(**data)
                self._accounts[prof.account_id] = prof
            except Exception:
                continue

    def _save_account(self, profile: AccountProfile) -> None:
        file = self._get_account_file(profile.account_id)
        file.write_text(json.dumps(asdict(profile), indent=2), encoding="utf-8")

    def _ensure_defaults(self) -> None:
        """Pre-populate Gunjan's 4 distinct niche Instagram accounts if not present."""
        if "gunjan_ai_tech" not in self._accounts:
            self.register_account(AccountProfile(
                account_id="gunjan_ai_tech",
                owner_name="Gunjan",
                platform="instagram",
                handle="@gunjan.ai_automation",
                niche="AI Agents, No-Code Tech & Workflow Automation",
                target_audience="Founders, creators, developers, tech enthusiasts looking to automate work",
                tone="Authoritative, innovative, fast-paced, high value, futuristic",
                upload_time="19:00 IST",
                posting_frequency="1 Reel/Day",
                preferred_hooks=[
                    "Stop doing [boring manual task] in 2026. Use this AI setup instead.",
                    "Nobody is talking about this hidden AI workflow that saves 15 hours a week.",
                    "If you're still not using personal AI agents, you're falling behind.",
                ],
                hashtag_pool=["#AIAutomation", "#ArtificialIntelligence", "#TechTrends", "#AIAgents", "#ProductivityHacks"],
                cta_templates=["Comment 'AI' and I'll send the direct workflow setup link!", "Save this reel before you forget!"],
                brand_rules=["Always show real workflow proof on screen", "Keep transitions snappy (under 1.5s per cut)"],
            ))

        if "gunjan_fitness" not in self._accounts:
            self.register_account(AccountProfile(
                account_id="gunjan_fitness",
                owner_name="Gunjan",
                platform="instagram",
                handle="@gunjan.fitmatrix",
                niche="Fitness, Calisthenics & High Performance Body Composition",
                target_audience="Busy professionals and youth wanting peak physical shape with smart routines",
                tone="Disciplined, energetic, motivating, science-backed, direct",
                upload_time="07:30 IST",
                posting_frequency="1 Reel/Day",
                preferred_hooks=[
                    "The real reason your bench press is stuck (and it's not your chest).",
                    "3 daily habits that helped me stay lean without starving.",
                    "Stop making this 1 huge mistake in your workout routine.",
                ],
                hashtag_pool=["#FitnessMotivation", "#Calisthenics", "#WorkoutRoutine", "#HighPerformance", "#HealthHabits"],
                cta_templates=["Share this with your gym partner!", "Drop a 🔥 if you're hitting the gym today!"],
                brand_rules=["Focus on clean form and energy", "High-energy background audio"],
            ))

        if "gunjan_finance" not in self._accounts:
            self.register_account(AccountProfile(
                account_id="gunjan_finance",
                owner_name="Gunjan",
                platform="instagram",
                handle="@gunjan.alphatrader",
                niche="Finance, Stock Market & Trading Psychology",
                target_audience="Traders, investors, and business people looking for risk-managed market alpha",
                tone="Calculated, analytical, calm, risk-conscious, wealth-focused",
                upload_time="08:45 IST",
                posting_frequency="1 Reel/Day",
                preferred_hooks=[
                    "90% of retail traders lose money because of this single psychological flaw.",
                    "How professional risk management beats fancy technical indicators every time.",
                    "Here is the exact trading framework I use before placing any order.",
                ],
                hashtag_pool=["#StockMarketIndia", "#TradingStrategy", "#WealthMindset", "#FinanceTips", "#RiskManagement"],
                cta_templates=["Save this risk checklist for market open tomorrow!", "Comment 'CHART' for breakdown!"],
                brand_rules=["Never give financial advice disclaimers skipped", "Show real risk-to-reward ratios"],
            ))

        if "gunjan_lifestyle" not in self._accounts:
            self.register_account(AccountProfile(
                account_id="gunjan_lifestyle",
                owner_name="Gunjan",
                platform="instagram",
                handle="@gunjan.lifestyle",
                niche="Mindset, Personal Mastery, Tech Nomad Lifestyle",
                target_audience="Ambitious creators, remote builders, modern entrepreneurs",
                tone="Inspirational, aesthetic, authentic, storytelling, high-vibe",
                upload_time="20:30 IST",
                posting_frequency="1 Reel/Day",
                preferred_hooks=[
                    "The uncomfortable truth about building freedom in your 20s.",
                    "What happens when you cut out all distractions for 30 straight days.",
                    "A day in the life of building autonomous AI systems from scratch.",
                ],
                hashtag_pool=["#MindsetMatters", "#CreatorEconomy", "#PersonalGrowth", "#DigitalNomad", "#DeepWork"],
                cta_templates=["Save this for when you need that reminder.", "Tag someone who needs to hear this."],
                brand_rules=["Aesthetic cinematic b-roll", "Warm color grading"],
            ))

    def register_account(self, profile: AccountProfile) -> AccountProfile:
        self._accounts[profile.account_id] = profile
        self._save_account(profile)
        return profile

    def get_account(self, account_id: str) -> AccountProfile | None:
        return self._accounts.get(account_id)

    def list_accounts(self) -> list[AccountProfile]:
        return list(self._accounts.values())


class ViralContentEngine:
    """Generates viral hooks, dialogue scripts, and 30-day content calendars with zero client bleed."""

    def __init__(self, workspace_manager: ClientWorkspaceManager | None = None):
        self.workspaces = workspace_manager or ClientWorkspaceManager()

    def generate_30day_content_plan(
        self,
        account_id: str,
        *,
        focus_topic: str = "",
        month_name: str = "Upcoming Month",
    ) -> dict[str, Any]:
        account = self.workspaces.get_account(account_id)
        if not account:
            raise ValueError(f"Account '{account_id}' not found. Please register the account profile first.")

        plan_items: list[ContentItem] = []
        topic_base = focus_topic or account.niche

        # Hook patterns & formula templates
        hook_types = [
            ("Pattern Interrupt", f"Stop making this rookie mistake with {account.niche.split(',')[0]}."),
            ("Curiosity Gap", f"The secret 3-step framework top 1% use for {topic_base}."),
            ("Contrarian Truth", f"Why everything you've been told about {topic_base} is wrong."),
            ("Story / Transformation", f"How I went from 0 to complete mastery in {topic_base}."),
            ("Urgent Problem Fix", f"If you're struggling with {topic_base}, watch this 30-second fix."),
        ]

        for day in range(1, 31):
            htype, htext = hook_types[(day - 1) % len(hook_types)]
            hook_full = f"[0-3s HOOK]: \"{htext}\""
            
            script = (
                f"[Visual: Fast hook cut on screen showing live example]\n"
                f"[Audio/Dialogue]: \"{htext} Most people ignore this, but here is what actually works.\"\n"
                f"[Visual: Step 1 text on screen + demonstration]\n"
                f"[Audio/Dialogue]: \"Step 1: Simplify your core setup. Step 2: Implement daily consistency. Step 3: Track metrics with precision.\"\n"
                f"[Visual: Screen showing final verified output]\n"
                f"[Audio/Dialogue]: \"{account.cta_templates[day % len(account.cta_templates)]}\""
            )

            caption = (
                f"🔥 {htext}\n\n"
                f"When building in {account.niche}, consistency and the right systems make all the difference.\n\n"
                f"📌 Save this post for later!\n"
                f"👇 {account.cta_templates[day % len(account.cta_templates)]}\n\n"
                f"{' '.join(account.hashtag_pool[:5])}"
            )

            item = ContentItem(
                day_number=day,
                title=f"Day {day}: {account.niche.split(',')[0]} Breakdown #{day}",
                niche=account.niche,
                content_format="Reel / Short",
                hook_3s=hook_full,
                script_dialogue=script,
                cta=account.cta_templates[day % len(account.cta_templates)],
                caption=caption,
                hashtags=account.hashtag_pool[:5],
                scheduled_time=account.upload_time,
                status="Scheduled / Ready",
            )
            plan_items.append(item)

        # Export to isolated formatted Excel file
        excel_svc = get_local_excel_service()
        filename = f"{account.account_id}_30day_content_plan.xlsx"
        headers = [
            "Day", "Title", "Format", "Scheduled Time", "0-3s Hook",
            "Video Script & Dialogue", "CTA", "Caption & Hashtags", "Status",
        ]
        rows = [
            [
                f"Day {it.day_number}",
                it.title,
                it.content_format,
                it.scheduled_time,
                it.hook_3s,
                it.script_dialogue,
                it.cta,
                it.caption,
                it.status,
            ]
            for it in plan_items
        ]
        excel_path = excel_svc.create_spreadsheet(
            filename,
            headers,
            rows,
            sheet_name=f"{account.handle} 30D Plan",
        )

        # Also write clean markdown deliverable
        md_dir = Path("services/brain/data/artifacts") / f"agency_{account.account_id}"
        md_dir.mkdir(parents=True, exist_ok=True)
        md_path = md_dir / "30day_content_calendar.md"

        md_content = [
            f"# 30-Day Content & Video Calendar: {account.handle}",
            f"**Owner/Client:** {account.owner_name} | **Niche:** {account.niche}",
            f"**Upload Time:** {account.upload_time} | **Platform:** {account.platform.title()}",
            f"**Excel Deliverable:** [{excel_path.name}](file:///{str(excel_path).replace('\\', '/')})\n",
            "---",
        ]
        for it in plan_items[:7]:  # Preview first 7 days in MD
            md_content.append(f"### Day {it.day_number}: {it.title}")
            md_content.append(f"- **Scheduled Time:** `{it.scheduled_time}`")
            md_content.append(f"- **0-3s Hook:** {it.hook_3s}")
            md_content.append(f"- **Script / Dialogue:**\n```\n{it.script_dialogue}\n```")
            md_content.append(f"- **Caption:**\n```\n{it.caption}\n```")
            md_content.append("---\n")

        md_content.append(f"\n*Full 30-day rows available in Excel deliverable: `{excel_path}`*")
        md_path.write_text("\n".join(md_content), encoding="utf-8")

        # Register in file knowledge index
        try:
            from app.knowledge.project_index import get_project_knowledge
            p_svc = get_project_knowledge()
            p_svc.register_file(
                excel_path,
                category="client_deliverable",
                purpose=f"30-Day social media content calendar for {account.handle} ({account.niche})",
                why_created=f"Owner request for {account.owner_name} {account.platform} campaign",
                tags=["social_media", "instagram", "content_calendar", account.account_id],
            )
            p_svc.register_file(
                md_path,
                category="client_deliverable",
                purpose=f"30-Day video scripts and hooks document for {account.handle}",
                why_created=f"Scripts and dialogue preparation for {account.handle}",
                tags=["scripts", "dialogue", "hooks", account.account_id],
            )
        except Exception:
            pass

        return {
            "account_id": account.account_id,
            "owner": account.owner_name,
            "handle": account.handle,
            "niche": account.niche,
            "total_days_planned": len(plan_items),
            "excel_file": str(excel_path),
            "markdown_file": str(md_path),
            "first_day_preview": asdict(plan_items[0]),
        }


_default_viral_engine: ViralContentEngine | None = None

def get_viral_content_engine() -> ViralContentEngine:
    global _default_viral_engine
    if _default_viral_engine is None:
        _default_viral_engine = ViralContentEngine()
    return _default_viral_engine
