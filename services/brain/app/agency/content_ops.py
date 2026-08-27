"""
VYOM Scalable Multi-Tenant Agency & Client Content Operating System
===================================================================
Provides dynamic, fully customizable multi-client and multi-account workspace management.
Scales effortlessly from 1 account to 100+ clients without hardcoded limits or fixed niches.

Capabilities:
- Dynamic Account Management (Create, Update, Delete, List, Search any brand/client)
- Custom Niche & Persona Configuration (Niche, Tone, Schedule, Hashtags, CTA, Rules)
- Scalable 30-Day Viral Content Engine (Hooks, Line-by-line dialogue scripts, visual cues)
- Isolated Deliverables (.xlsx Excel spreadsheets + .md packages)
- Zero Cross-Client Data Bleed
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Sequence
from uuid import uuid4

from app.sheets.local_excel import get_local_excel_service

AGENCY_STORAGE_DIR = Path("services/brain/data/agency_workspaces")


@dataclass
class AccountProfile:
    account_id: str
    owner_name: str
    platform: str  # 'instagram', 'youtube', 'linkedin', 'twitter', 'tiktok', 'threads'
    handle: str
    niche: str
    target_audience: str
    tone: str
    upload_time: str  # e.g. "18:30 IST"
    posting_frequency: str = "1 post/day"
    preferred_hooks: list[str] = field(default_factory=list)
    hashtag_pool: list[str] = field(default_factory=list)
    cta_templates: list[str] = field(default_factory=list)
    brand_rules: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


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
    """Dynamic multi-tenant workspace manager scaling from 1 to 100+ client accounts."""

    def __init__(self, base_dir: Path | None = None):
        self.base_dir = base_dir or AGENCY_STORAGE_DIR
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._accounts: dict[str, AccountProfile] = {}
        self._load()

    def _get_account_file(self, account_id: str) -> Path:
        safe_id = account_id.strip().lower().replace(" ", "_")
        return self.base_dir / f"{safe_id}_profile.json"

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

    def create_or_update_account(self, profile: AccountProfile) -> AccountProfile:
        """Create or update any arbitrary client/brand account profile."""
        if not profile.account_id:
            profile.account_id = f"acc_{uuid4().hex[:8]}"
        self._accounts[profile.account_id] = profile
        self._save_account(profile)
        return profile

    def get_account(self, account_id: str) -> AccountProfile | None:
        return self._accounts.get(account_id)

    def delete_account(self, account_id: str) -> bool:
        if account_id in self._accounts:
            del self._accounts[account_id]
            file = self._get_account_file(account_id)
            if file.exists():
                file.unlink()
            return True
        return False

    def list_accounts(
        self,
        owner_filter: str | None = None,
        platform_filter: str | None = None,
    ) -> list[AccountProfile]:
        res = list(self._accounts.values())
        if owner_filter:
            res = [a for a in res if owner_filter.lower() in a.owner_name.lower()]
        if platform_filter:
            res = [a for a in res if platform_filter.lower() == a.platform.lower()]
        return res

    def search_accounts(self, query: str) -> list[AccountProfile]:
        q = query.lower()
        return [
            a for a in self._accounts.values()
            if q in a.account_id.lower() or q in a.owner_name.lower() or q in a.handle.lower() or q in a.niche.lower()
        ]


class ViralContentEngine:
    """Generates viral hooks, dialogue scripts, and 30-day content calendars dynamically for any niche."""

    def __init__(self, workspace_manager: ClientWorkspaceManager | None = None):
        self.workspaces = workspace_manager or ClientWorkspaceManager()

    def generate_30day_content_plan(
        self,
        account_id_or_profile: str | AccountProfile,
        *,
        focus_topic: str = "",
        month_name: str = "Upcoming Month",
    ) -> dict[str, Any]:
        """Dynamically generates 30-day viral plan for any registered or on-the-fly profile."""
        if isinstance(account_id_or_profile, AccountProfile):
            account = account_id_or_profile
        else:
            account = self.workspaces.get_account(account_id_or_profile)
            if not account:
                # If not found, try searching or create an on-the-fly profile for custom niche
                matches = self.workspaces.search_accounts(account_id_or_profile)
                if matches:
                    account = matches[0]
                else:
                    # Dynamically instantiate a custom profile for this query
                    account = AccountProfile(
                        account_id=f"custom_{account_id_or_profile.lower().replace(' ', '_')[:32]}",
                        owner_name="Client",
                        platform="instagram",
                        handle=f"@{account_id_or_profile.lower().replace(' ', '_')}",
                        niche=account_id_or_profile,
                        target_audience=f"Target audience for {account_id_or_profile}",
                        tone="Engaging, high-value, authentic, authoritative",
                        upload_time="19:00 IST",
                        preferred_hooks=[
                            f"Stop making this rookie mistake with {account_id_or_profile}.",
                            f"The 3-step framework for mastering {account_id_or_profile}.",
                        ],
                        hashtag_pool=[f"#{w}" for w in account_id_or_profile.split()[:4]],
                        cta_templates=["Comment below for details!", "Save this post for later!"],
                    )

        plan_items: list[ContentItem] = []
        topic_base = focus_topic or account.niche
        niche_core = account.niche.split(",")[0].strip()

        # Dynamic Hook Generator Formulas
        hook_types = [
            ("Pattern Interrupt", f"Stop doing {niche_core} the old way in 2026. Here is the modern approach."),
            ("Curiosity Gap", f"The secret 3-step framework top 1% use for {topic_base}."),
            ("Contrarian Truth", f"Why everything you've been told about {niche_core} is wrong."),
            ("Story / Transformation", f"How to go from 0 to complete mastery in {topic_base}."),
            ("Urgent Problem Fix", f"If you're struggling with {niche_core}, watch this 30-second fix."),
            ("Framework Breakdown", f"The exact step-by-step blueprint for {niche_core}."),
            ("Mistake Warning", f"The #1 mistake destroying your progress in {niche_core}."),
        ]

        ctas = account.cta_templates or [
            "Comment 'INFO' below to get the direct guide!",
            "Save this reel before you forget!",
            "Share this with someone who needs to see it!",
        ]

        hashtags = account.hashtag_pool or [
            f"#{niche_core.replace(' ', '')}",
            "#TrendingReels",
            "#ViralGrowth",
            "#CreatorStrategy",
            "#DailyValue",
        ]

        for day in range(1, 31):
            htype, htext = hook_types[(day - 1) % len(hook_types)]
            hook_full = f"[0-3s HOOK ({htype})]: \"{htext}\""
            selected_cta = ctas[(day - 1) % len(ctas)]

            script = (
                f"[Visual: Fast cut high-energy demonstration of {niche_core}]\n"
                f"[Audio/Dialogue]: \"{htext} Here is what actually works.\"\n"
                f"[Visual: Step 1 text on screen with kinetic animation]\n"
                f"[Audio/Dialogue]: \"Step 1: Simplify your foundation. Step 2: Implement daily consistency. Step 3: Track metrics with precision.\"\n"
                f"[Visual: Verified result on screen + gesture to comment]\n"
                f"[Audio/Dialogue]: \"{selected_cta}\""
            )

            caption = (
                f"🔥 {htext}\n\n"
                f"When building in {account.niche}, consistency and the right systems make all the difference.\n\n"
                f"📌 Save this post for later!\n"
                f"👇 {selected_cta}\n\n"
                f"{' '.join(hashtags[:5])}"
            )

            item = ContentItem(
                day_number=day,
                title=f"Day {day}: {niche_core} Mastery #{day}",
                niche=account.niche,
                content_format="Reel / Short",
                hook_3s=hook_full,
                script_dialogue=script,
                cta=selected_cta,
                caption=caption,
                hashtags=hashtags[:5],
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
            sheet_name=f"{account.handle[:25]} 30D Plan",
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

        return {
            "account_id": account.account_id,
            "owner": account.owner_name,
            "handle": account.handle,
            "platform": account.platform,
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
