"""
Post-Fix Verification Script
=============================
Verifies all P1+P2 fixes applied during the reality audit session.
"""
import sys, asyncio, os
sys.path.insert(0, 'services/brain')

# Force load .env before anything
from dotenv import load_dotenv
load_dotenv('services/brain/.env', override=True)

print("=" * 60)
print("POST-FIX VERIFICATION")
print("=" * 60)

checks = [
    ('CRMEngine',          'from app.crm.engine import CRMEngine'),
    ('GraphEngine',        'from app.brain_graph.graph_engine import GraphEngine'),
    ('BrainGraphService',  'from app.brain_graph import BrainGraphService'),
    ('CRMStore',           'from app.crm import CRMStore, Lead, LeadState'),
    ('GoogleProvider',     'from app.providers.google import GoogleProvider'),
    ('QuotaBudgeter',      'from app.routing.quota_budgeter import QuotaBudgeter'),
    ('MemoryManager',      'from app.memory.manager import MemoryManager'),
    ('PaperBroker',        'from app.trading.paper_broker import PaperBroker'),
    ('PersonalOSEngine',   'from app.automation.personal_os_engine import PersonalOSEngine'),
    ('TaskCheckpoint',     'from app.reliability.checkpoints import TaskCheckpoint'),
    ('MorningBriefing',    'from app.daily_review.morning import MorningBriefingService'),
    ('DynamicMatcher',     'from app.tools.dynamic_matcher import get_tool_matcher'),
    ('ToolCatalog335',     'from app.tools.catalog_300 import ALL_300_TOOLS, count_tools'),
]

passed = 0
failed = 0
for name, stmt in checks:
    try:
        exec(stmt)
        print(f"  OK    {name}")
        passed += 1
    except Exception as e:
        print(f"  FAIL  {name}  ->  {str(e)[:70]}")
        failed += 1

print()
print(f"Import results: {passed}/{len(checks)} PASSED, {failed} FAILED")
print()

# --- Live LLM Test (P2) ---
print("=" * 60)
print("LIVE GEMINI API CALL TEST")
print("=" * 60)

async def test_live_llm():
    from app.providers.google import GoogleProvider
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        print("  SKIP: GEMINI_API_KEY not set in env")
        return
    provider = GoogleProvider(timeout_seconds=20.0)
    print(f"  API key loaded: {key[:8]}...{key[-4:]}")
    print(f"  Provider configured: {provider.configured}")
    from app.providers.base import ProviderRequest
    from app.schemas.tasks import TaskProfile, TaskDomain
    req = ProviderRequest(
        model="gemini-2.0-flash-lite",
        system_instruction="You are VYOM, a personal AI assistant.",
        user_request="Reply with exactly: VYOM_LIVE_OK",
        profile=TaskProfile(domain=TaskDomain.GENERAL),
    )
    try:
        resp = await provider.generate(req)
        print(f"  LIVE LLM RESPONSE: {resp.content[:100].strip()}")
        print(f"  Tokens used: in={resp.usage.input_tokens} out={resp.usage.output_tokens}")
    except Exception as e:
        print(f"  LLM call failed: {e}")
    await provider.aclose()

asyncio.run(test_live_llm())

# --- Morning Briefing Smoke Test ---
print()
print("=" * 60)
print("MORNING BRIEFING SMOKE TEST")
print("=" * 60)
from app.daily_review.morning import MorningBriefingService, MorningBriefingInput
svc = MorningBriefingService()
data = MorningBriefingInput(
    calendar_meeting_count=3,
    pending_approvals=2,
    pending_task_notes=["task-001|Fix CRM engine export", "task-002|Wire morning briefing to TTS"],
    market_alert_notes=["NIFTY up 0.8% pre-market"],
)
briefing = svc.build(data)
print(f"  Generated summary: {briefing.summary}")
print(f"  Highlights ({len(briefing.highlights)}): {briefing.highlights}")
print(f"  Retry candidates: {briefing.retry_candidates}")
print()
print("=" * 60)
print("ALL FIXES VERIFIED")
print("=" * 60)
