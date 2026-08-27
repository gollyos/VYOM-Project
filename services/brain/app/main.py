from __future__ import annotations

import asyncio
import contextlib
import os
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
import yaml
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

from app.api import agency, agents, alerts as alerts_api, adaptive as adaptive_api, approvals, artifacts as artifacts_api, automations, backtesting as backtesting_api, backup_api, booking as booking_api, brain_graph as brain_graph_api, calendar as calendar_api, capabilities, contacts, conversation as conversation_api, crm, curator as curator_api, delivery as delivery_api, desktop as desktop_api, devices as devices_api, diagnostics_api, discord as discord_api, discovery as discovery_api, email as email_api, extension as extension_api, facebook as facebook_api, finance as finance_api, goals as goals_api, habits as habits_api, health_api, integrations, kanban as kanban_api, knowledge as knowledge_api, learn as learn_api, markets as markets_api, mcp as mcp_api, meetings, memory, models, nodes as nodes_api, observability_api, paper_trading as paper_trading_api, personal as personal_api, plugins as plugins_api, production_api, quota, remote as remote_api, research as research_api, reviews as reviews_api, routines as routines_api, screen as screen_api, setup_api, sheets as sheets_api, skills, sync_api, tasks, telegram as telegram_api, tools, video as video_api, websocket, youtube as youtube_api, instagram as instagram_api, twitter as twitter_api, linkedin as linkedin_api, meta_ads as meta_ads_api, whatsapp as whatsapp_api, search as search_api
from app.agency.service import AgencyService, DisconnectedLeadResearchProvider
from app.agents.evaluator import AgentEvaluator
from app.agents.factory import AgentFactory
from app.agents.lifecycle import AgentLifecycle
from app.agents.registry import AgentRegistry
from app.agents.runtime import AgentRuntime
from app.browser.browser_actions import BrowserActions
from app.browser.browser_session import BrowserSession
from app.browser.browser_verifier import BrowserVerifier
from app.browser.playwright_manager import PlaywrightManager
from app.browser_extension.bridge import ExtensionBridge
from app.browser_extension.pairing import PairingStore
from app.core.config import Settings, get_settings, BRAIN_ROOT, PROJECT_ROOT
from app.core.logging import configure_logging
from app.capabilities.discovery import CapabilityDiscovery
from app.capabilities.registry import CapabilityRegistry
from app.capabilities.schemas import CapabilityRecord, CapabilitySource, CapabilityStatus, verified_now
from app.persistence.database import Database
from app.persistence.model_performance_store import ModelPerformanceStore
from app.persistence.task_store import TaskStore
from app.persistence.conversation_store import ConversationStore
from app.adaptive.curator import Curator, CuratorRunStore
from app.adaptive.dialectic_reasoner import DialecticReasoner
from app.plugins.registry import PluginRegistry
from app.kanban.store import KanbanStore, AgentMessageStore
from app.kanban.dispatcher import KanbanDispatcher
from app.skills.learn import LearnService
from app.providers import ProviderRegistry, create_provider_registry
from app.providers.response_cache import ResponseCache
from app.routing.model_registry import ModelRegistry
from app.routing.model_router import ModelRouter
from app.routing.provider_health import ProviderHealth
from app.routing.quota_budgeter import QuotaBudgeter
from app.routing.usage_tracker import UsageTracker
from app.runtime.llm_triage import LLMTriage
from app.runtime.event_bus import EventBus
from app.runtime.executor import Executor
from app.runtime.planner import Planner
from app.runtime.task_classifier import TaskClassifier
from app.runtime.task_runtime import TaskRuntime
from app.runtime.verifier import Verifier
from app.execution.action_engine import ActionEngine
from app.execution.evidence_collector import EvidenceCollector
from app.execution.execution_context import ExecutionContextFactory
from app.execution.process_manager import ProcessManager
from app.mcp.registry import MCPRegistry
from app.mcp.server_config import MCPConnectionManager, load_mcp_server_configs
from app.agents.autonomous_worker import AutonomousAgentWorker
from app.adaptive.auto_promotion import SkillAutoPromoter
from app.knowledge.store import KnowledgeStore
from app.knowledge.service import KnowledgeService
from app.artifacts.engine import ArtifactEngine
from app.artifacts.export_manager import ArtifactStore
from app.booking.reservation import BookingReservationService
from app.booking.search import BookingSearchService, MockBookingProvider
from app.booking.store import BookingStore
from app.delivery.client_delivery import ClientDeliveryService, DeliveryStore, MockDeliveryProvider
from app.discovery.engine import DiscoveryEngine
from app.discovery.saas_discovery import SubscriptionRegistry
from app.research.orchestrator import DeepResearchTask
from app.automation.personal_os_engine import PersonalOSEngine as Phase8Engine
from app.desktop.app_launcher import ApplicationRegistry, AppLauncher
from app.desktop.clipboard import ClipboardController
from app.desktop.controller import DesktopController
from app.desktop.notifications import NotificationDispatcher, NotificationPolicy
from app.desktop.startup import StartupController, WindowsRegistryStartupBackend
from app.desktop.system_status import SystemStatusService
from app.desktop.window_manager import WindowManager
from app.devices.authentication import DevicePairingService
from app.devices.heartbeat import HeartbeatMonitor
from app.devices.registry import DeviceRegistry
from app.devices.store import DeviceNodeStore, NodeTokenStore
from app.distributed import (
    ActivitySummaryBuilder,
    BudgetLimits,
    DistributedAuditLog,
    DistributedCoordinator,
    GlobalBudgetManager,
    LeaseManager,
    NodeRouter,
    RouterConfig,
    TaskDispatcher,
    TaskHandoffService,
    TaskOwnershipRegistry,
    TaskRequirements,
)
from app.distributed.schemas import RecoveryAction
from app.sync import ConflictResolver, OfflineCommandQueue, ReplicationManager, SyncEngine, SyncJournal
from app.sync.bridge import SyncEventBridge
from app.reliability import (
    CheckpointStore,
    CircuitBreakerRegistry,
    HealthAggregator,
    HealthState,
    RecoveryService,
    ReliabilityMetrics,
    Supervisor,
    Watchdog,
    WatchdogConfig,
)
from app.remote import (
    RemoteApprovalService,
    RemoteCommandGateway,
    RemoteNotificationRouter,
    RemoteSessionManager,
)
from app.remote.delivery import RemoteDeliveryBridge, RemoteDeliveryStore
from app.backup import BackupManager, RestoreService, SnapshotService
from app.security.authentication import LocalAuthPolicy, TrustMode, UserIdentity
from app.security.authorization import AuthorizationService
from app.security.credential_manager import CredentialManager, CredentialSpec
from app.security.rate_limits import GlobalRateLimits
from app.security.redaction import redact_mapping
from app.security.secret_store import SecretStore
from app.security.security_events import SecurityEventLog
from app.security.sessions import SessionSecurityManager
from app.observability import (
    CostTracker,
    CrashReporter,
    MetricsRegistry,
    PerformanceBudgets,
    PerformanceMonitor,
    StructuredLogging,
    Tracer,
)
from app.diagnostics import (
    DatabaseChecks,
    IntegrationChecks,
    ProviderChecks,
    SecurityAudit,
    SystemChecks,
    ToolChecks,
    VYOMDoctor,
)
from app.migrations.manager import MigrationManager
from app.production import (
    ConfigValidator,
    GracefulShutdown,
    ReadinessTracker,
    StartupChecks,
)
from app.production.middleware import ProductionMiddleware
from app.capabilities.external_intake import (
    CapabilityBackendRouter,
    ExternalCapabilityIntake,
)
from app.capabilities.schemas import CapabilityBackend, ExternalCapabilityMeta, ExternalCapabilityStatus
from app.integrations.composio import ComposioAdapter, MockComposioTransport
from app.mcp.codebase_memory import CodebaseMemoryAdapter, CodebaseMemoryTransport
from app.research.defuddle import DefuddleExtractor
from app.adaptive import (
    AdaptiveConfig,
    AdaptiveContextService,
    AdaptiveLearner,
    AdaptivePolicyEngine,
    ExperienceStore,
    StrategyEngine,
)
from app.adaptive.learner import AdaptiveLearningBridge
from app.adaptive.self_improvement import SafeSelfImprovement
from app.memory.namespaces import NamespaceMemoryRouter
from app.memory.resolution import ResolutionChain
from app.brain_graph import BrainGraphService
from app.workbench import UniversalWorkbench
from app.runtime.cognitive_runtime import CognitiveRuntime
from app.runtime.mission_loop import MissionLoop, MissionLimits
from app.runtime.planner import GeneralPlanner
from app.runtime.mission_packs import MISSION_PACKS, run_pack
from app.runtime.planner import ModelAssistedPlanner
from app.adaptive.learned_router import LearnedRouter
from app.adaptive.evaluator import ImprovementMetrics
from app.setup import (
    IntegrationSetup,
    OnboardingService,
    PermissionSetup,
    ProviderSetup,
    SetupStateStore,
)
from app.input_control.accessibility import NativeAccessibilityController
from app.input_control.keyboard import KeyboardController, PyAutoGuiKeyboardBackend
from app.input_control.mouse import MouseController, PyAutoGuiMouseBackend
from app.input_control.policy import EmergencyPauseState, InputSafetyPolicy
from app.native_apps.adapters.terminal import TerminalAdapter
from app.native_apps.adapters.vscode import VSCodeAdapter
from app.native_apps.capability_discovery import register_adapter_capabilities
from app.native_apps.registry import NativeAppAdapterRegistry
from app.desktop.execution_engine import DesktopExecutionEngine as Phase9Engine
from app.alerts.engine import AlertEngine
from app.alerts.store import AlertStore
from app.backtesting.engine import BacktestEngine
from app.finance.portfolio import PortfolioService
from app.finance.store import PortfolioStore, WatchlistStore
from app.market_data.candles import CandleService
from app.market_data.fundamentals import FundamentalsService
from app.market_data.freshness import FreshnessPolicy
from app.market_data.quotes import QuoteService
from app.market_data.registry import ProviderRegistry as MarketDataProviderRegistry
from app.market_intelligence.catalyst_analysis import CatalystResearcher
from app.market_intelligence.regime import RegimeClassifier
from app.market_intelligence.researcher import MarketResearcher
from app.market_intelligence.sentiment import SentimentAnalyzer
from app.market_intelligence.technical_analysis import TechnicalAnalysisEngine
from app.market_intelligence.thesis_builder import ThesisBuilder
from app.finance.intelligence_engine import FinancialIntelligenceEngine as Phase10Engine
from app.risk.engine import RiskEngine
from app.risk.kill_switch import PaperKillSwitch, RiskKillSwitch
from app.risk.rules import RiskRules
from app.strategies.registry import StrategyRegistry
from app.trading.journal import JournalService
from app.trading.paper_broker import PaperBroker
from app.trading.setup_builder import SetupBuilder
from app.trading.schemas import TradeDirection
from app.trading.store import JournalStore, PaperOrderStore
from app.trading.trade_manager import TradeManager
from app.chief_of_staff.orchestrator import ChiefOfStaffOrchestrator
from app.daily_review.evening import EveningReviewService
from app.daily_review.monthly import MonthlyReviewService
from app.daily_review.morning import MorningBriefingService
from app.daily_review.weekly import WeeklyReviewService
from app.goals.evaluator import GoalEvaluator
from app.goals.manager import GoalManager
from app.goals.milestones import MilestoneService
from app.goals.planner import GoalPlanner
from app.goals.progress import GoalProgressEvaluator
from app.goals.store import GoalStore, MilestoneStore
from app.habits.insights import HabitInsightService
from app.habits.interventions import InterventionEngine
from app.habits.pattern_analyzer import HabitPatternAnalyzer
from app.habits.store import HabitEventStore, HabitStore
from app.habits.streaks import StreakCalculator
from app.habits.tracker import HabitTracker
from app.notifications.delivery import NotificationDeliveryService, NotificationRecordStore
from app.notifications.preferences import NotificationPreferencesService
from app.notifications.quiet_hours import QuietModeState
from app.personal.commitments import CommitmentService
from app.personal.context_builder import PersonalContextBuilder
from app.personal.profile import PersonalProfileService
from app.personal.store import CommitmentStore, PersonalProfileStore
from app.productivity.chief_of_staff_engine import ChiefOfStaffEngine as Phase11Engine
from app.diagnostics.observability_engine import DiagnosticsObservabilityEngine as Phase13Engine
from app.proactive.engine import ProactiveEngine
from app.proactive.rules import ProactiveRules
from app.proactive.suppression import ProactiveSuggestionStore
from app.productivity.focus_sessions import FocusSessionService, FocusSessionStore
from app.productivity.workload import WorkloadCalculator
from app.routines.adaptation import RoutineAdaptationService
from app.routines.completion import RoutineCompletionService, RoutineStepExecutor
from app.routines.manager import RoutineManager
from app.routines.scheduler import RoutineScheduler
from app.routines.store import RoutineRunStore, RoutineStore
from app.schemas.tasks import TaskCreate
from app.screen.capture import ScreenCapture
from app.screen.observer import ScreenObserver
from app.screen.privacy_filter import PrivacyFilter
from app.memory.embeddings import (
    CachedEmbeddingProvider,
    DisabledEmbeddingProvider,
    EmbeddingProvider,
    GeminiEmbeddingProvider,
    LocalHashEmbeddingProvider,
)
from app.memory.vault import MemoryVault
from app.memory.manager import MemoryManager
from app.memory.retrieval import MemoryRetriever
from app.memory.store import MemoryStore
from app.learning.improvement_engine import ImprovementEngine
from app.learning.intelligence_engine import IntelligenceEngine
from app.automation.scheduler import AutomationScheduler
from app.automation.events import AutomationEventEngine
from app.automation.store import AutomationStore
from app.briefing.engine import BusinessEngine
from app.briefing.service import BriefingService
from app.calendar.provider import DisconnectedCalendarProvider
from app.integrations.google_oauth import GoogleOAuthClient
from app.messaging.telegram_provider import DisconnectedTelegramProvider, RealTelegramProvider
from app.messaging.telegram_service import TelegramService
from app.messaging.discord_provider import DisconnectedDiscordProvider, RealDiscordProvider
from app.messaging.discord_service import DiscordService
from app.sheets.provider import DisconnectedSheetsProvider, GoogleSheetsProvider, SHEETS_SCOPES
from app.sheets.service import SheetsService
from app.video.service import VideoService
from app.youtube.provider import DisconnectedYouTubeProvider, RealYouTubeProvider, YOUTUBE_SCOPES
from app.youtube.service import YouTubeService
from app.instagram.provider import DisconnectedInstagramProvider, RealInstagramProvider
from app.instagram.service import InstagramService
from app.facebook.provider import DisconnectedFacebookProvider, RealFacebookProvider
from app.facebook.service import FacebookService
from app.linkedin.provider import DisconnectedLinkedInProvider, RealLinkedInProvider
from app.linkedin.service import LinkedInService
from app.twitter.provider import DisconnectedTwitterProvider, RealTwitterProvider
from app.twitter.service import TwitterService
from app.safety.query_judge import QuerySafetyJudge
from app.meta_ads.provider import DisconnectedMetaAdsProvider, RealMetaAdsProvider
from app.meta_ads.service import MetaAdsService
from app.whatsapp.connector import WhatsAppConnector
from app.calendar.service import CalendarService
from app.contacts.resolver import ContactResolver
from app.crm.store import CRMStore
from app.email.provider import CombinedEmailProvider, DisconnectedEmailProvider, GmailAppPasswordProvider, GmailProvider, GMAIL_SCOPES
from app.email.service import EmailService
from app.integrations.registry import IntegrationRegistry
from app.integrations.secrets import UnavailableSecretVault, WindowsDPAPISecretVault
from app.meetings.service import MeetingService
from app.notifications.service import NotificationService
from app.security.command_policy import CommandPolicy
from app.security.permission_engine import PermissionEngine
from app.tools.executor import ToolExecutor
from app.tools.registry import ToolRegistry
from app.tools_builtin import BrowserTool, CryptoTool, CurrencyTool, DesktopTool, DiscordTool, EmailTool, FacebookTool, FilesystemTool, GitTool, ImageEditTool, InputControlTool, InstagramTool, LinkedInTool, MetaAdsTool, NewsTool, SafetyJudgeTool, ScreenObserveTool, ScreenshotTool, SheetsTool, SystemTool, TelegramTool, TerminalTool, TriviaFactsTool, TwitterTool, VideoTool, WeatherTool, WhatsAppTool, WikipediaTool, YouTubeTool
from app.tools_builtin.project_files import ProjectFileTool
from app.skills.builder import SkillBuilder
from app.skills.executor import SkillExecutor
from app.skills.teachable import TeachableSkillService
from app.skills.registry import SkillRegistry
from app.skills.sandbox import SkillSandbox


def create_app(
    settings: Settings | None = None,
    provider_registry: ProviderRegistry | None = None,
) -> FastAPI:
    selected_settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        # Boot profiling: cold start was measured at ~95s (bundled 3.11,
        # Aug 2026) and the desktop frontend gives up long before that.
        # Every major lifespan block logs its duration so the slow parts
        # are visible in data/logs/brain.log instead of guessed at.
        import logging as _logging
        import time as _time

        _boot_logger = _logging.getLogger("vyom-brain.boot")
        _boot_t0 = _time.perf_counter()
        _boot_mark = _time.perf_counter()

        def _boot_step(name: str) -> None:
            nonlocal _boot_mark
            now = _time.perf_counter()
            _boot_logger.info("boot.phase %s took %.2fs", name, now - _boot_mark)
            _boot_mark = now

        database = Database(selected_settings.database_path)
        await database.connect()
        task_store = TaskStore(database)
        conversation_store = ConversationStore(database)
        performance_store = ModelPerformanceStore(database)
        event_bus = EventBus()
        from app.runtime.progress_tracker import ProgressTracker
        progress_tracker = ProgressTracker()
        event_bus.add_observer(progress_tracker.observe)
        model_registry = ModelRegistry.from_yaml(selected_settings.model_registry_path)
        providers = provider_registry or create_provider_registry(selected_settings)
        provider_health = ProviderHealth()
        # Free-tier budgeting: pace requests BEFORE they are sent and fan
        # traffic out across sibling models (each has a separate daily
        # allowance), instead of discovering limits by slamming into them.
        # Attached the same way learned_router is - optional attribute, so
        # every existing construction path (tests, tools) keeps working.
        data_dir = selected_settings.database_path.parent
        # The Chrome extension bridge: real-browser access (real DOM, real
        # signed-in profile) alongside the isolated Playwright browser and
        # the UI-Automation desktop path. Built here (not lazily) so its
        # pairing token is stable and its bridge is a singleton every
        # ActionEngine call and every /api/extension/* request shares.
        extension_pairing = PairingStore(data_dir / "extension-pairing.json")
        extension_bridge = ExtensionBridge()
        quota_budgeter = QuotaBudgeter(data_dir / "quota-usage.json")
        response_cache = ResponseCache(data_dir / "response-cache")
        for provider in providers.providers.values():
            provider.response_cache = response_cache
            if hasattr(provider, "budgeter"):
                provider.budgeter = quota_budgeter
        usage_tracker = UsageTracker()
        tool_registry = ToolRegistry.from_yaml(selected_settings.tool_registry_path)
        playwright_manager = PlaywrightManager()
        browser_session = BrowserSession(playwright_manager)
        browser_actions = BrowserActions(browser_session)
        browser_verifier = BrowserVerifier(browser_session)
        evidence_collector = EvidenceCollector(selected_settings.audit_log_path)
        tool_executor = ToolExecutor(tool_registry, evidence_collector)
        context_factory = ExecutionContextFactory(selected_settings.allowed_roots)
        process_manager = ProcessManager(selected_settings.allowed_roots)
        project_root = selected_settings.allowed_roots[0]

        # -- Phase 9 desktop control stack ---------------------------------
        window_manager = WindowManager()
        application_registry = ApplicationRegistry.from_config(project_root / "config" / "applications.yaml")
        # Beyond the curated list above, teach the registry every app this
        # machine actually has installed (Start Menu shortcuts AND
        # packaged/Store apps, via Get-StartApps) so "open X" works for
        # anything on the user's PC, not only the ~10 apps someone typed
        # into applications.yaml. This shells out to PowerShell and takes
        # over a second - it runs exactly ONCE, here, off the event loop
        # via to_thread, before the server starts accepting requests, so
        # no live command ever pays that cost.
        await asyncio.to_thread(application_registry.discover_installed_apps)
        _boot_step("app-discovery")
        app_launcher = AppLauncher(application_registry)
        clipboard_controller = ClipboardController()
        notification_dispatcher = NotificationDispatcher(NotificationPolicy())
        system_status_service = SystemStatusService(project_root)
        startup_controller = StartupController(
            WindowsRegistryStartupBackend(),
            str(project_root / "src-tauri" / "target" / "release" / "vyom.exe"),
        )
        # Windows UI Automation is constructed BEFORE the desktop
        # controller so the controller can prefer semantic accessibility
        # over every lower tier. Previously this object existed but was
        # only reachable from the input-control tool, so no desktop
        # operation ever consulted the accessibility tree at all.
        native_accessibility = NativeAccessibilityController()
        desktop_controller = DesktopController(
            application_registry, app_launcher, window_manager, clipboard_controller,
            notification_dispatcher, system_status_service, startup_controller, process_manager,
            accessibility=native_accessibility,
        )
        native_app_adapters = NativeAppAdapterRegistry()
        native_app_adapters.register(VSCodeAdapter())
        native_app_adapters.register(TerminalAdapter())

        screen_capture = ScreenCapture()
        privacy_filter = PrivacyFilter()
        screen_observer = ScreenObserver(screen_capture, window_manager, privacy_filter)

        emergency_pause = EmergencyPauseState()
        input_safety_policy = InputSafetyPolicy(emergency_pause=emergency_pause)
        try:
            mouse_backend = PyAutoGuiMouseBackend()
        except Exception:
            mouse_backend = None
        try:
            keyboard_backend = PyAutoGuiKeyboardBackend()
        except Exception:
            keyboard_backend = None

        device_heartbeat = HeartbeatMonitor()
        # Phase 12: durable node registry/credentials so pairing,
        # trust, and revocation survive Brain restarts.
        node_store = DeviceNodeStore(database)
        token_store = NodeTokenStore(database)
        device_registry = DeviceRegistry(device_heartbeat, store=node_store)
        device_pairing = DevicePairingService(token_store=token_store)
        await device_pairing.load_tokens()
        await device_registry.hydrate()

        tool_registry.register(FilesystemTool())
        tool_registry.register(TerminalTool(CommandPolicy()))
        tool_registry.register(GitTool())
        tool_registry.register(BrowserTool(browser_actions, browser_verifier))
        tool_registry.register(ScreenshotTool(browser_actions, window_manager, privacy_filter))
        tool_registry.register(SystemTool())
        tool_registry.register(WeatherTool())
        tool_registry.register(CurrencyTool())
        tool_registry.register(CryptoTool())
        tool_registry.register(TriviaFactsTool())
        tool_registry.register(WikipediaTool())
        tool_registry.register(NewsTool())
        tool_registry.register(WhatsAppTool())
        tool_registry.register(ImageEditTool())
        tool_registry.register(DesktopTool(desktop_controller, native_app_adapters))
        tool_registry.register(ScreenObserveTool(screen_observer))
        tool_registry.register(ProjectFileTool())
        if mouse_backend is not None and keyboard_backend is not None:
            tool_registry.register(InputControlTool(native_accessibility, MouseController(mouse_backend, input_safety_policy), KeyboardController(keyboard_backend, input_safety_policy), input_safety_policy))
        action_engine = ActionEngine(
            executor=tool_executor,
            context_factory=context_factory,
            process_manager=process_manager,
            project_root=selected_settings.allowed_roots[0],
            application_registry=application_registry,
            task_store=task_store,
            extension_bridge=extension_bridge,
        )
        memory_config = yaml.safe_load(
            selected_settings.memory_config_path.read_text(encoding="utf-8")
        ) or {}
        memory_store = MemoryStore(
            database,
            vault=MemoryVault(data_dir / "memory-vault"),
        )
        embedding_config = memory_config.get("embeddings", {})
        local_embeddings = LocalHashEmbeddingProvider(int(embedding_config.get("dimensions", 96)))
        provider_name = embedding_config.get("provider", "local_hash")
        if provider_name == "gemini" and embedding_config.get("allow_remote", False):
            import os as _os

            base_provider: EmbeddingProvider | None = GeminiEmbeddingProvider(
                _os.getenv("GEMINI_API_KEY") or _os.getenv("GOOGLE_API_KEY"),
                fallback=local_embeddings,
            )
        elif provider_name == "local_hash":
            base_provider = local_embeddings
        else:
            base_provider = DisabledEmbeddingProvider()
        # Cache vectors in SQLite: a decade of memories must not be
        # re-embedded on every search.
        embedding_provider = CachedEmbeddingProvider(database, base_provider)
        memory_manager = MemoryManager(
            memory_store,
            MemoryRetriever(memory_store, embedding_provider),
        )

        # VYOM's own persistent, queryable knowledge base ("khud ka
        # Wikipedia"): a structured facts table (KnowledgeStore) plus a
        # mirror into the SAME durable memory/FTS5/embedding search every
        # other recall already uses (KnowledgeService). ask_or_research()
        # is the reusable "ask first, browse only if stale/missing" entry
        # point. Constructed here (not later) because the research task
        # built below needs it to record what it learns, and MemoryManager
        # + Database are already in scope.
        knowledge_store = KnowledgeStore(database)
        knowledge_service = KnowledgeService(knowledge_store, memory_manager)

        try:
            secret_vault = WindowsDPAPISecretVault(selected_settings.secret_store_path)
        except RuntimeError:
            secret_vault = UnavailableSecretVault()
        integration_registry = await IntegrationRegistry.from_yaml(
            selected_settings.integration_config_path, database, secret_vault
        )
        _boot_step("integration-registry")
        # Gmail and Sheets each get their OWN GoogleOAuthClient instance so
        # a user connecting one is never asked to also grant the other's
        # scopes (each is a separate consent screen against the SAME
        # Desktop-app OAuth client — one Cloud Console project, narrower
        # per-integration scopes). Real network/OAuth activates once
        # GOOGLE_OAUTH_CLIENT_ID/_SECRET are set; until then both behave
        # exactly like the disconnected stubs they replace.
        google_client_id = os.getenv("GOOGLE_OAUTH_CLIENT_ID", "")
        google_client_secret = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET", "")
        if google_client_id and google_client_secret:
            gmail_oauth = GoogleOAuthClient(google_client_id, google_client_secret, GMAIL_SCOPES)
            sheets_oauth = GoogleOAuthClient(google_client_id, google_client_secret, SHEETS_SCOPES)
            youtube_oauth = GoogleOAuthClient(google_client_id, google_client_secret, YOUTUBE_SCOPES)
            oauth_email_provider = GmailProvider(gmail_oauth, secret_vault)
            sheets_provider = GoogleSheetsProvider(sheets_oauth, secret_vault)
            youtube_provider = RealYouTubeProvider(youtube_oauth, secret_vault)
        else:
            oauth_email_provider = DisconnectedEmailProvider()
            sheets_provider = DisconnectedSheetsProvider()
            youtube_provider = DisconnectedYouTubeProvider()
        # App-Password Gmail is ALWAYS constructed (no client_id/secret
        # needed — it is the simple path specifically because it needs
        # none) and combined with whichever the OAuth path resolved to.
        # POST /api/email/app-password/connect activates it; until a user
        # calls that (or completes OAuth), CombinedEmailProvider.health()
        # honestly reports disconnected via both.
        app_password_provider = GmailAppPasswordProvider(secret_vault)
        instagram_provider = RealInstagramProvider(secret_vault)
        facebook_provider = RealFacebookProvider(secret_vault)
        twitter_provider = RealTwitterProvider(secret_vault)
        linkedin_provider = RealLinkedInProvider(secret_vault)
        meta_ads_provider = RealMetaAdsProvider(secret_vault)
        email_provider = CombinedEmailProvider(app_password_provider, oauth_email_provider)
        calendar_provider = DisconnectedCalendarProvider()
        if "gmail" in integration_registry.records:
            integration_registry.register_provider("gmail", email_provider)
        if "google-calendar" in integration_registry.records:
            integration_registry.register_provider("google-calendar", calendar_provider)
        if "google-sheets" in integration_registry.records:
            integration_registry.register_provider("google-sheets", sheets_provider)
        if "youtube" in integration_registry.records:
            integration_registry.register_provider("youtube", youtube_provider)
        if "instagram" in integration_registry.records:
            integration_registry.register_provider("instagram", instagram_provider)
        if "facebook" in integration_registry.records:
            integration_registry.register_provider("facebook", facebook_provider)
        if "linkedin" in integration_registry.records:
            integration_registry.register_provider("linkedin", linkedin_provider)
        if "twitter" in integration_registry.records:
            integration_registry.register_provider("twitter", twitter_provider)
        if "meta-ads" in integration_registry.records:
            integration_registry.register_provider("meta-ads", meta_ads_provider)
        crm_store = CRMStore(database, memory=memory_manager)
        email_service = EmailService(database, email_provider)
        calendar_service = CalendarService(calendar_provider)
        sheets_service = SheetsService(sheets_provider)
        youtube_service = YouTubeService(youtube_provider)
        instagram_service = InstagramService(instagram_provider)
        facebook_service = FacebookService(facebook_provider)
        twitter_service = TwitterService(twitter_provider)
        linkedin_service = LinkedInService(linkedin_provider)
        meta_ads_service = MetaAdsService(meta_ads_provider)
        whatsapp_connector = WhatsAppConnector(
            connector_dir=Path(__file__).resolve().parent.parent / "whatsapp_connector",
            auth_data_dir=data_dir / "whatsapp-auth",
            # VYOM_NODE_BIN points at the bundled portable Node runtime
            # when the installed app sets it (src-tauri spawns the Brain
            # with this env var pointing at resources/runtime/node/node.exe)
            # - falls back to "node" on PATH for dev-mode runs that never
            # went through scripts/prepare-bundled-runtimes.sh.
            node_bin=os.getenv("VYOM_NODE_BIN", "node"),
        )
        # Telegram authenticates with a single bot token (from @BotFather),
        # not OAuth. It's read from TELEGRAM_BOT_TOKEN if set, otherwise
        # from a token stored via the self-service POST
        # /api/telegram/connect endpoint (same pattern as Instagram/
        # Meta-Ads' access-token connect) — env var wins if both exist.
        telegram_bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        if not telegram_bot_token:
            stored_telegram_token = secret_vault.get("token:telegram")
            if stored_telegram_token:
                telegram_bot_token = stored_telegram_token.decode("utf-8")
        telegram_provider = (
            RealTelegramProvider(telegram_bot_token) if telegram_bot_token
            else DisconnectedTelegramProvider()
        )
        telegram_service = TelegramService(database, telegram_provider)
        if "telegram" in integration_registry.records:
            integration_registry.register_provider("telegram", telegram_provider)
        # Discord mirrors Telegram's bot-token connect exactly (Developer
        # Portal -> New Application -> Bot -> Copy Token, no OAuth) — read
        # from DISCORD_BOT_TOKEN if set, otherwise from a token stored via
        # POST /api/discord/connect.
        discord_bot_token = os.getenv("DISCORD_BOT_TOKEN", "")
        if not discord_bot_token:
            stored_discord_token = secret_vault.get("token:discord")
            if stored_discord_token:
                import json as _json
                try:
                    discord_bot_token = _json.loads(stored_discord_token.decode("utf-8")).get("bot_token", "")
                except (ValueError, AttributeError):
                    discord_bot_token = ""
        discord_provider = RealDiscordProvider(secret_vault)
        if discord_bot_token:
            discord_provider.store_credentials(discord_bot_token)
        discord_service = DiscordService(discord_provider)
        if "discord" in integration_registry.records:
            integration_registry.register_provider("discord", discord_provider)
        video_service = VideoService(workdir=data_dir / "video-jobs")
        # Registered here (not with the other built-in tools above) because
        # they depend on email_service/sheets_service, which depend on the
        # OAuth-aware providers constructed just above — registering earlier
        # would mean registering against the disconnected stubs unconditionally.
        tool_registry.register(EmailTool(email_service))
        tool_registry.register(SheetsTool(sheets_service))
        tool_registry.register(TelegramTool(telegram_service))
        tool_registry.register(DiscordTool(discord_service))
        tool_registry.register(VideoTool(video_service))
        tool_registry.register(YouTubeTool(youtube_service))
        query_safety_judge = QuerySafetyJudge()
        tool_registry.register(SafetyJudgeTool(query_safety_judge))
        application.state.query_safety_judge = query_safety_judge
        tool_registry.register(InstagramTool(instagram_service))
        tool_registry.register(FacebookTool(facebook_service))
        tool_registry.register(TwitterTool(twitter_service))
        tool_registry.register(LinkedInTool(linkedin_service))
        tool_registry.register(MetaAdsTool(meta_ads_service))
        contact_resolver = ContactResolver()
        agency_service = AgencyService(crm_store, email_service, DisconnectedLeadResearchProvider())
        meeting_service = MeetingService(calendar_service, crm_store, contact_resolver, database)
        automation_store = AutomationStore(database)
        notification_service = NotificationService()

        capability_registry = await CapabilityRegistry.from_tools(tool_registry)
        # Capability truth for the action path: ActionEngine consults this
        # LIVE registry before executing or before reporting an inability,
        # so "I cannot browse / access files / control the PC" can only
        # ever come from real registry state, never from model knowledge.
        action_engine.capability_registry = capability_registry
        capability_discovery = CapabilityDiscovery(capability_registry)
        for integration in integration_registry.list():
            capability_discovery.from_integration(integration)
        for model in model_registry.enabled():
            provider = providers.get(model.provider)
            capability_discovery.from_model(
                model,
                available=bool(provider and provider.configured),
            )
        skill_registry = SkillRegistry(selected_settings.skills_root)
        learn_service = LearnService(skill_registry)
        skill_registry.load()
        for registered_skill in skill_registry.list():
            capability_discovery.from_skill(registered_skill)
        skill_sandbox = SkillSandbox(capability_registry, tool_registry)
        skill_builder = SkillBuilder(skill_registry, skill_sandbox)
        skill_executor = SkillExecutor(skill_registry, action_engine)
        teachable_skills = TeachableSkillService(skill_registry, tool_registry)

        agent_registry = AgentRegistry(selected_settings.agents_root)
        agent_registry.load()
        agent_registry.seed(selected_settings.agent_config_path)
        agent_evaluator = AgentEvaluator(capability_registry, skill_registry, tool_registry)
        agent_factory = AgentFactory(agent_registry, agent_evaluator)
        agent_lifecycle = AgentLifecycle(agent_registry)
        agent_runtime = AgentRuntime(agent_registry, agent_lifecycle, skill_executor)

        # -- Multi-agent orchestrator --------------------------------------
        from app.agents.multi_agent_orchestrator import MultiAgentOrchestrator
        multi_agent_orchestrator = MultiAgentOrchestrator(
            agent_registry=agent_registry,
            agent_runtime=agent_runtime,
            event_bus=event_bus,
        )

        # Self-monitoring, proactive, meta-learning, trust scoring, and heartbeat
        # are initialized AFTER the adaptive stack below (they depend on
        # adaptive_experience_store). See the block after adaptive_learner.

        for registered_agent in agent_registry.list():
            capability_discovery.from_agent(registered_agent)
        for capability_id, name, description, tags in (
            ("research.deep_research", "Deep Research", "Multi-source research with ranked sources, contradiction detection, and citations", ["research", "phase8"]),
            ("browser_agent.semantic_action", "Browser Agent", "Semantic browser navigation with bounded recovery", ["browser", "phase8"]),
            ("discovery.recommend", "Capability Discovery", "Capability/subscription/API/MCP/SaaS discovery and recommendation", ["discovery", "phase8"]),
            ("booking.search", "Booking Search", "Bounded booking search/compare across configured providers", ["booking", "phase8"]),
            ("artifacts.create_report", "Artifact Engine", "Generates and validates professional reports/diagrams/spreadsheets/presentations", ["artifacts", "phase8"]),
            ("delivery.package", "Client Delivery", "Quality-gated client delivery packaging with duplicate prevention", ["delivery", "phase8"]),
        ):
            capability_registry.register(CapabilityRecord(
                capability_id=capability_id, name=name, description=description,
                source=CapabilitySource.BUILTIN_TOOL, source_id="phase8-engine",
                status=CapabilityStatus.AVAILABLE, reliability=0.8, last_verified=verified_now(), tags=tags,
            ))
        for capability_id, name, description, tags in (
            ("desktop.app_launch", "Application Launching", "Registered-executable app open/focus/close/status", ["desktop", "phase9"]),
            ("desktop.window_manage", "Window Management", "Native OS window list/focus/move/resize/minimize/maximize", ["desktop", "phase9"]),
            ("desktop.clipboard", "Clipboard Control", "Deliberate, single-shot clipboard read/write/clear", ["desktop", "phase9"]),
            ("desktop.system_status", "System Status", "Safe CPU/memory/storage/battery/network metrics", ["desktop", "phase9"]),
            ("desktop.startup", "Startup Preference", "User-controlled launch-at-login enable/disable/status", ["desktop", "phase9"]),
            ("screen.capture", "Screen Capture", "On-request full/monitor/window/region screenshot capture", ["screen", "phase9"]),
            ("screen.observe", "Screen Understanding", "Structured ScreenObservation of the active window", ["screen", "phase9"]),
            ("input_control.accessibility", "Accessibility Automation", "Semantic, label-based native app control", ["input", "phase9"]),
            ("input_control.fallback", "Input Fallback", "Bounded, policy-checked mouse/keyboard fallback automation", ["input", "phase9"]),
            ("devices.pairing", "Device Node Pairing", "Authenticated device pairing/heartbeat/command routing foundation", ["devices", "phase9"]),
        ):
            capability_registry.register(CapabilityRecord(
                capability_id=capability_id, name=name, description=description,
                source=CapabilitySource.BUILTIN_TOOL, source_id="phase9-engine",
                status=CapabilityStatus.AVAILABLE, reliability=0.8, last_verified=verified_now(), tags=tags,
            ))
        register_adapter_capabilities(capability_registry, native_app_adapters)
        for capability_id, name, description, tags in (
            ("market_data.quotes", "Market Data", "Provider-independent quote/candle/fundamentals access with freshness labeling", ["finance", "phase10"]),
            ("finance.portfolio_analytics", "Portfolio Analytics", "P&L, exposure, concentration, drawdown, volatility analytics", ["finance", "phase10"]),
            ("trading.thesis", "Trading Analysis", "Technical analysis, regime classification, catalyst research, evidence-backed thesis", ["finance", "phase10"]),
            ("trading.paper_broker", "Paper Broker", "Simulated market/limit/stop order execution against a local PAPER portfolio", ["finance", "phase10"]),
            ("risk.engine", "Risk Engine", "Structured PASS/REDUCE/REJECT risk decisions for proposed trades and portfolios", ["finance", "phase10"]),
            ("backtesting.engine", "Backtest Engine", "Deterministic historical strategy simulation with lookahead protection", ["finance", "phase10"]),
            ("strategies.registry", "Strategy Registry", "Versioned, structured StrategySpec storage and evaluation", ["finance", "phase10"]),
            ("alerts.engine", "Market Alerts", "Deterministic price/technical/portfolio alert condition checking with cooldown", ["finance", "phase10"]),
        ):
            capability_registry.register(CapabilityRecord(
                capability_id=capability_id, name=name, description=description,
                source=CapabilitySource.BUILTIN_TOOL, source_id="phase10-engine",
                status=CapabilityStatus.AVAILABLE, reliability=0.8, last_verified=verified_now(), tags=tags,
            ))
        for capability_id, name, description, tags in (
            ("goals.manage", "Goal Management", "Structured goals with evidence-based progress and milestone tracking", ["personal", "phase11"]),
            ("habits.track", "Habit Tracking", "Explicit-check-in habit tracking with pattern analysis and evidence-gated insights", ["personal", "phase11"]),
            ("routines.manage", "Routine Management", "Structured routines executed through the existing permission-gated tool layer", ["personal", "phase11"]),
            ("focus.manage", "Focus Sessions", "Focus session lifecycle with notification suppression while active", ["personal", "phase11"]),
            ("reviews.generate", "Daily/Weekly/Monthly Reviews", "Evidence-based morning briefing, evening/weekly/monthly reviews", ["personal", "phase11"]),
            ("chief_of_staff.brief", "Chief of Staff", "Cross-domain prioritization, risk/opportunity detection, and single-recommendation planning", ["personal", "phase11"]),
            ("commitments.track", "Commitment Tracking", "Tracks promises across explicit statements, meetings, email, and tasks", ["personal", "phase11"]),
        ):
            capability_registry.register(CapabilityRecord(
                capability_id=capability_id, name=name, description=description,
                source=CapabilitySource.BUILTIN_TOOL, source_id="phase11-engine",
                status=CapabilityStatus.AVAILABLE, reliability=0.8, last_verified=verified_now(), tags=tags,
            ))

        improvement_engine = ImprovementEngine(
            memory_manager,
            minimum_confidence=float(
                memory_config.get("learning", {}).get("minimum_lesson_confidence", 0.65)
            ),
        )
        intelligence_engine = IntelligenceEngine(
            memory=memory_manager,
            capabilities=capability_registry,
            skill_registry=skill_registry,
            skill_builder=skill_builder,
            skill_executor=skill_executor,
            agent_registry=agent_registry,
            agent_factory=agent_factory,
            agent_runtime=agent_runtime,
            action_engine=action_engine,
            improvement=improvement_engine,
            project_id=(
                "project-"
                + selected_settings.allowed_roots[0].name.lower().replace(" ", "-")
            ),
        )
        briefing_service = BriefingService(
            integration_registry, crm_store, email_service, calendar_service,
            automation_store, task_store,
        )
        business_engine = BusinessEngine(
            briefing_service, agency_service, crm_store, email_service,
            automation_store, integration_registry,
        )

        mcp_registry = MCPRegistry()
        # Auto-connect: every server declared in config/tools.yaml's
        # mcp_servers list is spawned and its tools registered into the
        # SAME tool_registry every other capability uses, so the planner,
        # agents, and skills can call an MCP tool exactly like a built-in
        # one — no per-server wiring anywhere else in the app. A server
        # that fails to start is recorded as errored and never blocks
        # boot; VYOM degrades gracefully rather than refusing to start.
        mcp_manager = MCPConnectionManager(mcp_registry, tool_registry, project_root)
        configured_mcp_servers = load_mcp_server_configs(selected_settings.tool_registry_path)
        research_config = DeepResearchTask.load_config(selected_settings.research_config_path)
        stored_serpapi_key = secret_vault.get("token:serpapi")
        research_task = DeepResearchTask.from_config(
            research_config, browser_actions=browser_actions, knowledge_service=knowledge_service,
            serpapi_key=stored_serpapi_key.decode("utf-8") if stored_serpapi_key else None,
        )
        subscription_registry = SubscriptionRegistry()
        discovery_engine = DiscoveryEngine(capability_registry, research_task, subscription_registry, mcp_registry)

        booking_store = BookingStore(database)
        # Booking providers default to disconnected, matching the Phase 7
        # lead-research honesty pattern; MockBookingProvider is test-only.
        booking_search_service = BookingSearchService({})
        booking_reservation_service = BookingReservationService(booking_search_service, booking_store)

        artifact_store = ArtifactStore(database)
        artifact_engine = ArtifactEngine(selected_settings.artifacts_root, artifact_store)

        delivery_store = DeliveryStore(database)
        client_delivery_service = ClientDeliveryService(delivery_store)

        phase8_engine = Phase8Engine(
            research_task=research_task,
            discovery_engine=discovery_engine,
            booking_search=booking_search_service,
            booking_reservation=booking_reservation_service,
            artifact_engine=artifact_engine,
            delivery_service=client_delivery_service,
            crm_store=crm_store,
        )
        # Research synthesis written by the model over the SAME extracted
        # claims (never from its own knowledge); deterministic template
        # remains the fallback, so offline research still works.
        phase8_engine.synthesis_provider = providers.get("google")
        phase8_engine.synthesis_model = next(
            (m.model_id for m in model_registry.enabled() if m.provider == "google"),
            None,
        )
        phase9_engine = Phase9Engine(
            tool_executor=tool_executor,
            context_factory=context_factory,
            desktop=desktop_controller,
            adapters=native_app_adapters,
            screen_observer=screen_observer,
            project_root=project_root,
            screenshots_root=project_root / "data" / "screenshots",
        )

        # -- Phase 10 finance/trading stack ---------------------------------
        market_data_config = MarketDataProviderRegistry.load_config(project_root / "config" / "market_data.yaml")
        market_data_registry = MarketDataProviderRegistry.from_config(market_data_config)
        market_freshness_policy = FreshnessPolicy.from_config(market_data_config)
        quote_service = QuoteService(market_data_registry, market_freshness_policy)
        candle_service = CandleService(market_data_registry)
        fundamentals_service = FundamentalsService(market_data_registry)

        technical_engine = TechnicalAnalysisEngine()
        regime_classifier = RegimeClassifier()
        catalyst_researcher = CatalystResearcher(research_task)
        sentiment_analyzer = SentimentAnalyzer()
        thesis_builder = ThesisBuilder()
        market_researcher = MarketResearcher(
            quote_service, candle_service, technical_engine, regime_classifier,
            catalyst_researcher, sentiment_analyzer, thesis_builder,
        )

        portfolio_store = PortfolioStore(database, memory=memory_manager)
        watchlist_store = WatchlistStore(database)
        portfolio_service = PortfolioService(portfolio_store, quote_service)

        risk_rules = RiskRules.from_yaml(project_root / "config" / "risk.yaml")
        risk_kill_switch = RiskKillSwitch(risk_rules)
        risk_engine = RiskEngine(risk_rules, risk_kill_switch)
        paper_kill_switch = PaperKillSwitch()

        paper_order_store = PaperOrderStore(database)
        paper_broker = PaperBroker(portfolio_store, paper_order_store, quote_service)
        setup_builder = SetupBuilder()
        trade_manager = TradeManager(risk_engine, paper_broker)
        journal_store = JournalStore(database)
        journal_service = JournalService(journal_store)

        strategy_registry = StrategyRegistry(database)
        backtest_engine = BacktestEngine(candle_service, database)

        alert_store = AlertStore(database)
        alert_engine = AlertEngine(alert_store)

        phase10_engine = Phase10Engine(
            market_researcher=market_researcher,
            setup_builder=setup_builder,
            trade_manager=trade_manager,
            paper_broker=paper_broker,
            backtest_engine=backtest_engine,
            strategy_registry=strategy_registry,
            portfolio_store=portfolio_store,
            watchlist_store=watchlist_store,
            journal_store=journal_store,
            alert_engine=alert_engine,
            risk_rules=risk_rules,
        )

        # -- Phase 11 personal OS / Chief of Staff stack --------------------
        personal_config = PersonalProfileService.load_config(project_root / "config" / "personal.yaml")
        personal_profile_store = PersonalProfileStore(database)
        personal_profile_service = PersonalProfileService(personal_profile_store, personal_config)
        commitment_store = CommitmentStore(database)
        commitment_service = CommitmentService(commitment_store)
        personal_context_builder = PersonalContextBuilder()

        goal_store = GoalStore(database, memory=memory_manager)
        milestone_store = MilestoneStore(database)
        milestone_service = MilestoneService(milestone_store)
        goals_config = yaml.safe_load((project_root / "config" / "goals.yaml").read_text(encoding="utf-8")) or {}
        goal_planner = GoalPlanner(
            max_milestones=int(goals_config.get("planning", {}).get("max_initial_milestones", 4)),
            max_next_actions=int(goals_config.get("planning", {}).get("max_initial_next_actions", 3)),
        )
        goal_progress_evaluator = GoalProgressEvaluator()
        goal_manager = GoalManager(goal_store, milestone_service, goal_planner, goal_progress_evaluator)
        neglect_config = goals_config.get("neglect_detection", {})
        goal_evaluator = GoalEvaluator(
            deferred_threshold=int(neglect_config.get("deferred_threshold", 3)),
            stale_days_threshold=int(neglect_config.get("stale_days_threshold", 21)),
        )

        habits_config = yaml.safe_load((project_root / "config" / "habits.yaml").read_text(encoding="utf-8")) or {}
        habit_store = HabitStore(database, memory=memory_manager)
        habit_event_store = HabitEventStore(database)
        habit_allowed_sources = set(habits_config.get("tracking", {}).get("allowed_sources", []))
        habit_tracker = HabitTracker(habit_store, habit_event_store, allowed_sources=habit_allowed_sources)
        pattern_config = habits_config.get("pattern_analysis", {})
        habit_pattern_analyzer = HabitPatternAnalyzer(
            minimum_sample_size=int(pattern_config.get("minimum_sample_size", 5)),
            minimum_confidence=float(pattern_config.get("minimum_confidence", 0.55)),
        )
        habit_streak_calculator = StreakCalculator()
        habit_intervention_engine = InterventionEngine()
        habit_insight_service = HabitInsightService(habit_pattern_analyzer, habit_streak_calculator, habit_intervention_engine)

        routine_store = RoutineStore(database)
        routine_run_store = RoutineRunStore(database)
        routine_manager = RoutineManager(routine_store)
        routine_step_executor = RoutineStepExecutor()

        async def _routine_reminder(payload: dict) -> str:
            from app.notifications.priority import NotificationPriority

            notification = await notification_delivery_service.deliver(
                payload.get("title", "Routine reminder"), payload.get("body", ""), priority=NotificationPriority.NORMAL,
            )
            return "delivered" if notification else "suppressed by quiet mode"

        async def _routine_open_application(payload: dict) -> str:
            status = app_launcher.open(str(payload.get("app_id", "")))
            return f"opened {status.app_id} (pid {status.pid})"

        async def _routine_start_focus_mode(payload: dict) -> str:
            session = await focus_session_service.start(str(payload.get("goal", "Routine focus block")), planned_minutes=float(payload.get("minutes", 25)))
            return f"focus session {session.id} started"

        async def _routine_create_task(payload: dict) -> str:
            from app.schemas.tasks import ActionProvenance

            created = await runtime.create_task(
                TaskCreate(user_request=str(payload.get("request", ""))),
                provenance=ActionProvenance.APPROVED_AUTOMATION,
            )
            return f"task {created.id} created"

        async def _routine_show_briefing(payload: dict) -> str:
            briefing = await briefing_service.generate()
            return briefing.summary

        routine_step_executor.register("reminder", _routine_reminder)
        routine_step_executor.register("open_application", _routine_open_application)
        routine_step_executor.register("start_focus_mode", _routine_start_focus_mode)
        routine_step_executor.register("create_task", _routine_create_task)
        routine_step_executor.register("show_briefing", _routine_show_briefing)

        routine_completion_service = RoutineCompletionService(routine_step_executor, routine_run_store)
        routine_scheduler = RoutineScheduler(routine_store, automation_store)
        routines_config = yaml.safe_load((project_root / "config" / "routines.yaml").read_text(encoding="utf-8")) or {}
        routine_adaptation_config = routines_config.get("adaptation", {})
        routine_adaptation_service = RoutineAdaptationService(
            routine_run_store,
            failure_streak_threshold=int(routine_adaptation_config.get("failure_streak_threshold", 3)),
            lookback_runs=int(routine_adaptation_config.get("lookback_runs", 10)),
        )

        focus_session_store = FocusSessionStore(database)
        focus_session_service = FocusSessionService(focus_session_store)
        workload_calculator = WorkloadCalculator()

        chief_of_staff_orchestrator = ChiefOfStaffOrchestrator()

        notifications_config = yaml.safe_load((project_root / "config" / "notifications.yaml").read_text(encoding="utf-8")) or {}
        proactive_rules = ProactiveRules.from_config(notifications_config)
        proactive_suggestion_store = ProactiveSuggestionStore(database)
        proactive_engine = ProactiveEngine(proactive_rules, proactive_suggestion_store)
        quiet_mode = QuietModeState()
        notification_record_store = NotificationRecordStore(database)
        notification_delivery_service = NotificationDeliveryService(notification_service, quiet_mode, notification_record_store)
        notification_preferences_service = NotificationPreferencesService(personal_profile_service)

        morning_briefing_service = MorningBriefingService()
        evening_review_service = EveningReviewService()
        weekly_review_service = WeeklyReviewService()
        monthly_review_service = MonthlyReviewService()

        phase11_engine = Phase11Engine(
            personal_profile_service=personal_profile_service, commitment_service=commitment_service,
            context_builder=personal_context_builder, goal_manager=goal_manager, goal_evaluator=goal_evaluator,
            milestone_service=milestone_service, habit_store=habit_store, habit_event_store=habit_event_store,
            habit_insight_service=habit_insight_service, routine_manager=routine_manager,
            routine_completion_service=routine_completion_service, focus_service=focus_session_service,
            workload_calculator=workload_calculator, chief_of_staff=chief_of_staff_orchestrator,
            quiet_mode=quiet_mode, morning_service=morning_briefing_service, evening_service=evening_review_service,
            weekly_service=weekly_review_service, crm_store=crm_store, task_store=task_store,
        )
        intelligence_engine.personal_profile_service = personal_profile_service

        async def execute_automation(definition):
            if definition.action == "run_vyom_command":
                from app.schemas.tasks import ActionProvenance, TaskCreate, TaskStatus

                command = str((definition.condition or {}).get("command", "")).strip()
                if not command:
                    raise RuntimeError("Scheduled VYOM command is empty")
                is_event_trigger = definition.type.value == "conditional"
                origin = "automation" if is_event_trigger else "schedule"
                created = await runtime.create_task(
                    TaskCreate(
                        user_request=command,
                        context_id=f"{origin}:{definition.id}",
                        source=f"{origin}:{definition.id}",
                        correlation_id=f"{origin}:{definition.id}:{definition.run_count + 1}",
                    ),
                    provenance=(ActionProvenance.APPROVED_AUTOMATION if is_event_trigger
                                else ActionProvenance.APPROVED_SCHEDULE),
                )
                deadline = asyncio.get_running_loop().time() + definition.budget.max_runtime_seconds
                while asyncio.get_running_loop().time() < deadline:
                    current = await task_store.get(created.id)
                    if current and current.status in {
                        TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED,
                        TaskStatus.NEEDS_APPROVAL, TaskStatus.PAUSED,
                    }:
                        if current.status == TaskStatus.COMPLETED:
                            return {
                                "summary": current.result.response if current.result else "Scheduled task completed",
                                "acted": True,
                                "task_id": current.id,
                                "task_status": current.status.value,
                                "goal_verification": current.metadata.get("goal_verification"),
                            }
                        if current.status in {TaskStatus.NEEDS_APPROVAL, TaskStatus.PAUSED}:
                            return {
                                "summary": "Scheduled task is waiting for required approval",
                                "acted": False,
                                "awaiting_approval": True,
                                "task_id": current.id,
                                "task_status": current.status.value,
                            }
                        raise RuntimeError(current.error or f"Scheduled task ended as {current.status.value}")
                    await asyncio.sleep(0.05)
                raise TimeoutError(f"Scheduled task {created.id} exceeded its runtime budget")
            if definition.action == "prepare_agency_briefing":
                briefing = await briefing_service.generate()
                return {"summary": briefing.summary, "generated_at": briefing.generated_at.isoformat()}
            if definition.action == "run_research_task":
                goal = str(definition.condition.get("goal")) if definition.condition else "General research"
                result = await research_task.run(goal)
                return {"summary": result.synthesis, "confidence": result.confidence, "generated_at": result.generated_at.isoformat()}
            if definition.action == "paper_trade_strategy":
                # Rule 51: automated PAPER execution requires the named
                # strategy to have been explicitly switched to `paper_auto`
                # by the user beforehand — the automation itself only runs
                # at L1 (deterministic condition check); it never silently
                # gains L2 authority. Every run still passes through the
                # Risk Engine and always produces a journal entry.
                condition = definition.condition or {}
                strategy_name = str(condition.get("strategy_name", ""))
                strategy_version = str(condition.get("strategy_version", ""))
                symbol = str(condition.get("symbol", ""))
                spec = await strategy_registry.get(strategy_name, strategy_version)
                if spec is None:
                    raise RuntimeError(f"Unknown strategy {strategy_name} v{strategy_version}")
                if spec.approval_mode != "paper_auto":
                    return {"summary": f"{strategy_name} v{strategy_version} is not paper_auto; skipping this run", "acted": False}

                series = await candle_service.get_candles(symbol, spec.timeframe, 220)
                from app.strategies.evaluator import StrategyEvaluator as _Evaluator, compute_fields as _compute_fields
                evaluator = _Evaluator()
                fields = _compute_fields(series.candles, len(series.candles) - 1)
                prev_fields = _compute_fields(series.candles, len(series.candles) - 2) if len(series.candles) > 1 else None
                if not evaluator.should_enter(spec, fields, prev_fields):
                    return {"summary": f"No entry condition met for {symbol} this run", "acted": False}

                quote = await quote_service.get_quote(symbol)
                stale_window = float(market_data_config.get("data_quality", {}).get("max_stale_seconds_before_pause", 1800))
                if market_freshness_policy.is_stale_for_decision(quote, max_age_seconds=stale_window):
                    risk_kill_switch.check_stale_data(True)
                    return {"summary": f"Market data for {symbol} exceeds the staleness window; paper automation paused rather than acted on", "acted": False}
                snapshot = technical_engine.analyze(symbol, spec.timeframe, series.candles)
                fallback_thesis_confidence = float(spec.risk_rules.get("risk_percentage", risk_rules.max_risk_per_trade_pct))
                from app.trading.schemas import TradeThesis as _TradeThesis
                thesis = _TradeThesis(
                    instrument=symbol, direction=TradeDirection.LONG, time_horizon=spec.timeframe,
                    thesis=f"Automated paper_auto entry for strategy {strategy_name} v{strategy_version}: structured entry rules satisfied.",
                    invalidation="Exit rules satisfied", confidence=0.5, data_timestamp=snapshot.as_of,
                )
                setup = setup_builder.build(thesis, snapshot, current_price=quote.price)
                portfolio = await paper_broker.get_or_create_portfolio(starting_cash=risk_rules.starting_cash, base_currency=risk_rules.base_currency)
                proposal = await trade_manager.propose(
                    setup, portfolio, account_size=portfolio.total_value() or risk_rules.starting_cash,
                    risk_percentage=fallback_thesis_confidence, approved=True,
                )
                if proposal.order is not None and proposal.order.status.value == "filled":
                    entry = await journal_service.open_entry(
                        portfolio_id=portfolio.id, symbol=symbol, direction=setup.direction, entry_order=proposal.order,
                        setup_id=setup.id, thesis_id=thesis.id, risk_amount=setup.max_risk,
                        sources=["local-fixture"], models_involved=["local-strategy-evaluator-v1"],
                    )
                    return {"summary": f"PAPER order filled for {symbol} ({strategy_name})", "acted": True, "order_id": proposal.order.order_id, "journal_id": entry.id}
                return {"summary": f"Risk Engine {proposal.risk_decision.decision.value} for {symbol}: {'; '.join(proposal.risk_decision.reasons) or 'no order placed'}", "acted": False}
            if definition.action == "run_routine":
                condition = definition.condition or {}
                routine_id = str(condition.get("routine_id", ""))
                routine = await routine_store.get(routine_id)
                if routine is None:
                    raise RuntimeError(f"Unknown routine {routine_id}")
                if not routine.enabled:
                    return {"summary": f"Routine '{routine.name}' is not enabled; skipping this run", "acted": False}
                run = await routine_completion_service.run(routine)
                return {"summary": f"Routine '{routine.name}' finished with status {run.status.value}", "acted": True, "run_id": run.id}
            raise RuntimeError("Automation action is not registered")

        automation_scheduler = AutomationScheduler(automation_store, execute_automation)
        curator_run_store = CuratorRunStore(database)
        plugin_registry = PluginRegistry()
        plugin_registry.discover_and_load(
            BRAIN_ROOT / "plugins",
            Path(os.getenv("VYOM_PLUGINS_DIR", str(PROJECT_ROOT / "data" / "plugins"))),
        )
        kanban_store = KanbanStore(database)
        agent_message_store = AgentMessageStore(database)
        kanban_dispatcher = KanbanDispatcher(
            kanban_store, base_url=f"http://{selected_settings.host}:{selected_settings.port}",
        )
        curator = Curator(
            task_store=task_store,
            run_store=curator_run_store,
            knowledge_service=knowledge_service,
            automation_store=automation_store,
            conversation_store=conversation_store,
            dialectic_reasoner=DialecticReasoner(conversation_store, knowledge_service),
            event_bus=event_bus,
        )
        automation_events = AutomationEventEngine(automation_store, automation_scheduler, event_bus)
        model_router = ModelRouter(
            model_registry,
            providers,
            performance_store,
            provider_health,
        )
        model_router.budgeter = quota_budgeter
        # Give the free-form autonomous agent path (AgentRuntime.delegate
        # for a skill-less agent) a real ReAct worker, wired to the SAME
        # tool_registry/tool_executor/model_router/providers/provider_health
        # every other execution path already uses — attached post-hoc,
        # exactly like model_router.learned_router below, so it never
        # disturbs agent_runtime's earlier construction order.
        autonomous_worker = AutonomousAgentWorker(
            tool_registry=tool_registry,
            tool_executor=tool_executor,
            model_router=model_router,
            providers=providers,
            provider_health=provider_health,
            default_allowed_roots=tuple(selected_settings.allowed_roots),
        )
        agent_runtime.autonomous_worker = autonomous_worker
        runtime = TaskRuntime(
            task_store=task_store,
            performance_store=performance_store,
            event_bus=event_bus,
            model_registry=model_registry,
            providers=providers,
            model_router=model_router,
            provider_health=provider_health,
            classifier=TaskClassifier(),
            planner=Planner(selected_settings.planning_complexity_threshold),
            executor=Executor(),
            verifier=Verifier(),
            permission_engine=PermissionEngine(),
            usage_tracker=usage_tracker,
            action_engine=action_engine,
            intelligence_engine=intelligence_engine,
            business_engine=business_engine,
            phase8_engine=phase8_engine,
            phase9_engine=phase9_engine,
            phase10_engine=phase10_engine,
            phase11_engine=phase11_engine,
        )

        # -- Phase 12 persistent multi-device runtime stack -----------------
        reliability_config = yaml.safe_load(
            (project_root / "config" / "reliability.yaml").read_text(encoding="utf-8")
        ) or {}
        runtime_config = yaml.safe_load(
            (project_root / "config" / "runtime.yaml").read_text(encoding="utf-8")
        ) or {}
        reliability_section = reliability_config.get("reliability", {})
        lease_manager = LeaseManager(
            database,
            default_ttl_seconds=int(reliability_config.get("leases", {}).get("default_ttl_seconds", 120)),
        )
        distributed_audit = DistributedAuditLog(database)
        budget_fields = BudgetLimits.__dataclass_fields__
        budget_manager = GlobalBudgetManager(
            database,
            BudgetLimits(**{
                key: (float(value) if key == "daily_model_cost" else int(value))
                for key, value in runtime_config.get("budgets", {}).items()
                if key in budget_fields
            }),
        )
        ownership_registry = TaskOwnershipRegistry(database, lease_manager)
        runtime.ownership_registry = ownership_registry  # duplicate-consequential-execution guard, see task_runtime.py::run()
        node_router = NodeRouter(device_registry, RouterConfig(local_node_id="brain-local"))
        checkpoint_store = CheckpointStore(database)
        task_dispatcher = TaskDispatcher(
            node_router, lease_manager, distributed_audit,
            budgets=budget_manager, event_bus=event_bus,
        )
        task_handoff_service = TaskHandoffService(
            node_router, lease_manager, distributed_audit, event_bus=event_bus,
        )

        def _requirements_resolver(task_id: str) -> TaskRequirements:
            # Default: tasks are treated as portable research-style work;
            # callers that know better pass explicit requirements.
            return TaskRequirements()

        coordinator = DistributedCoordinator(
            device_registry, lease_manager, distributed_audit,
            event_bus=event_bus, handoff=task_handoff_service,
            automation_store=automation_store,
            requirements_resolver=_requirements_resolver,
        )

        sync_journal = SyncJournal(database, origin_node="brain-local")
        conflict_resolver = ConflictResolver(database)
        sync_engine = SyncEngine(sync_journal, conflict_resolver, event_bus)
        offline_queue = OfflineCommandQueue(database, event_bus)
        replication_manager = ReplicationManager(device_registry, sync_journal)
        sync_bridge = SyncEventBridge(event_bus, sync_journal)

        health_aggregator = HealthAggregator(event_bus)
        reliability_metrics = ReliabilityMetrics()

        async def _check_database():
            return HealthState.HEALTHY if database.connection is not None else HealthState.OFFLINE

        async def _check_task_runtime():
            return HealthState.HEALTHY if emergency_pause.paused is False else HealthState.DEGRADED

        async def _check_scheduler():
            worker = getattr(automation_scheduler, "_worker", None)
            return HealthState.HEALTHY if worker is not None and not worker.done() else HealthState.OFFLINE

        async def _check_providers():
            return HealthState.HEALTHY if any(p.configured for p in providers.all()) else HealthState.UNKNOWN

        async def _check_tools():
            return HealthState.HEALTHY if tool_registry.list() else HealthState.DEGRADED

        async def _check_nodes():
            states = [node.online.value for node in device_registry.list()]
            if not states:
                return HealthState.UNKNOWN
            return HealthState.DEGRADED if "degraded" in states else HealthState.HEALTHY

        async def _check_email():
            return HealthState.HEALTHY if "gmail" in integration_registry.records else HealthState.UNKNOWN

        async def _check_calendar():
            return (
                HealthState.HEALTHY
                if "google-calendar" in integration_registry.records
                else HealthState.UNKNOWN
            )

        async def _check_mcp():
            return HealthState.UNKNOWN  # no external MCP transport configured yet

        async def _check_browser_worker():
            return HealthState.UNKNOWN  # playwright starts lazily; never probed by health polling

        async def _check_brain():
            return HealthState.HEALTHY

        health_aggregator.register("brain", _check_brain)
        health_aggregator.register("database", _check_database)
        health_aggregator.register("task_runtime", _check_task_runtime)
        health_aggregator.register("model_providers", _check_providers)
        health_aggregator.register("tool_registry", _check_tools)
        health_aggregator.register("mcp", _check_mcp)
        health_aggregator.register("email", _check_email)
        health_aggregator.register("calendar", _check_calendar)
        health_aggregator.register("browser_worker", _check_browser_worker)
        health_aggregator.register("desktop_mobile_nodes", _check_nodes)
        health_aggregator.register("automation_scheduler", _check_scheduler)

        breaker_config = reliability_config.get("circuit_breakers", {})
        circuit_breakers = CircuitBreakerRegistry(
            failure_threshold=int(breaker_config.get("failure_threshold", 5)),
            cooldown_seconds=float(breaker_config.get("cooldown_seconds", 60)),
            event_bus=event_bus,
        )
        watchdog_config_section = reliability_config.get("supervisor", {})
        watchdog = Watchdog(
            WatchdogConfig(
                stall_seconds=float(watchdog_config_section.get("stall_seconds", 300)),
                max_recovery_attempts=int(watchdog_config_section.get("max_recovery_attempts", 3)),
                repeated_failure_threshold=int(watchdog_config_section.get("repeated_failure_threshold", 3)),
            ),
            reliability_metrics,
        )
        recovery_service = RecoveryService(
            task_store, checkpoint_store, ownership_registry, distributed_audit, lease_manager,
        )

        remote_sessions = RemoteSessionManager(database)
        remote_command_gateway = RemoteCommandGateway(
            database, device_registry, remote_sessions, distributed_audit,
            permission_engine=PermissionEngine(), event_bus=event_bus,
        )
        remote_approvals = RemoteApprovalService(
            task_store, runtime, distributed_audit, event_bus,
            approval_ttl_seconds=int(reliability_config.get("approvals", {}).get("remote_ttl_seconds", 1800)),
        )
        remote_notification_router = RemoteNotificationRouter(sync_journal)
        remote_delivery_store = RemoteDeliveryStore(database)
        remote_delivery_bridge = RemoteDeliveryBridge(event_bus, task_store, remote_delivery_store)

        backup_config = reliability_config.get("backup", {})
        snapshot_service = SnapshotService(
            selected_settings.database_path,
            roots=[project_root / "config", project_root / "data"],
        )
        backup_manager = BackupManager(
            database, snapshot_service, selected_settings.backup_root, event_bus,
            retention=int(backup_config.get("retention", 10)),
            schedule=str(backup_config.get("schedule", "manual")),
        )
        restore_service = RestoreService(selected_settings.database_path, distributed_audit)
        activity_summary = ActivitySummaryBuilder(task_store, automation_store, distributed_audit)

        supervisor = Supervisor(
            coordinator, health_aggregator, lease_manager, reliability_metrics,
            poll_seconds=float(watchdog_config_section.get("poll_seconds", 30)),
            automation_store=automation_store,
        )

        # -- Phase 13 production-hardening stack ----------------------------
        security_config = yaml.safe_load(
            (project_root / "config" / "security.yaml").read_text(encoding="utf-8")
        ) or {}
        observability_config = yaml.safe_load(
            (project_root / "config" / "observability.yaml").read_text(encoding="utf-8")
        ) or {}
        release_config = yaml.safe_load(
            (project_root / "config" / "release.yaml").read_text(encoding="utf-8")
        ) or {}

        logs_dir = selected_settings.database_path.parent / "logs"
        structured_logging = StructuredLogging(
            logs_dir,
            level=str(observability_config.get("logging", {}).get("level", "INFO")),
            max_bytes=int(observability_config.get("logging", {}).get("max_file_bytes", 5_000_000)),
            backups=int(observability_config.get("logging", {}).get("backups", 5)),
        )
        log_file = structured_logging.apply()

        secret_store = SecretStore.for_local_machine(
            selected_settings.secret_store_path,
            metadata_path=selected_settings.database_path.parent / "secret-metadata.json",
        )
        credential_manager = CredentialManager(secret_store)
        for provider_name, env_name in (
            ("openai", "OPENAI_API_KEY"), ("anthropic", "ANTHROPIC_API_KEY"),
            ("google", "GEMINI_API_KEY"), ("openrouter", "OPENROUTER_API_KEY"),
            ("deepseek", "DEEPSEEK_API_KEY"), ("kimi", "MOONSHOT_API_KEY"),
        ):
            credential_manager.register(CredentialSpec(
                consumer=f"provider:{provider_name}",
                ref=SecretStore.build_ref("provider", provider_name),
                env_fallback=env_name,
            ))

        session_security = SessionSecurityManager(
            ttl_seconds=int(security_config.get("sessions", {}).get("ttl_seconds", 3600)),
            max_sessions_per_device=int(security_config.get("sessions", {}).get("max_per_device", 3)),
        )
        authorization_service = AuthorizationService("balanced")
        global_rate_limits = GlobalRateLimits.from_config(security_config)
        security_events = SecurityEventLog(selected_settings.database_path.parent / "security-audit.jsonl")

        metrics_registry = MetricsRegistry()
        tracer = Tracer(max_spans=int(observability_config.get("tracing", {}).get("max_spans", 1000)))
        performance_monitor = PerformanceMonitor(
            metrics_registry, PerformanceBudgets.from_config(observability_config),
        )
        cost_tracker = CostTracker(metrics_registry, performance_store)
        runtime.cost_tracker = cost_tracker  # live per-call cost/token recording; summary() also reads persisted model_performance
        crash_reporter = CrashReporter(
            selected_settings.database_path.parent / "crash-reports",
            app_version=str(release_config.get("app_version", "0.2.0")),
            service_version=str(release_config.get("brain_version", "0.2.0")),
        )

        migration_manager = MigrationManager(database)
        config_validator = ConfigValidator(project_root / "config")
        startup_checks = StartupChecks(
            config_validator=config_validator,
            database=database,
            migrations=migration_manager,
            secret_store=secret_store,
            required_dirs=[
                selected_settings.database_path.parent,
                selected_settings.skills_root,
                selected_settings.agents_root,
                selected_settings.artifacts_root,
                selected_settings.backup_root,
            ],
        )
        readiness_tracker = ReadinessTracker()

        system_checks = SystemChecks(required_dirs=[selected_settings.database_path.parent])
        database_checks = DatabaseChecks(selected_settings.database_path)
        doctor = VYOMDoctor(
            system_checks=system_checks,
            database_checks=database_checks,
            provider_checks=ProviderChecks(model_registry, providers),
            tool_checks=ToolChecks(tool_registry),
            integration_checks=IntegrationChecks(integration_registry, mcp_registry, device_registry),
            extra_checks={
                "automation_scheduler": (lambda: HealthState.HEALTHY
                                         if getattr(automation_scheduler, "_worker", None) is not None
                                         and not automation_scheduler._worker.done()
                                         else HealthState.DEGRADED),
                "device_nodes": (lambda: HealthState.HEALTHY
                                 if any(n.trust_level.value == "trusted" for n in device_registry.list())
                                 or not device_registry.list()
                                 else HealthState.UNKNOWN),
            },
        )
        doctor.migrations = migration_manager
        security_audit = SecurityAudit(
            database=database,
            settings_paths=sorted((project_root / "config").glob("*.yaml")),
            log_files=[log_file],
            security_config=security_config,
            device_registry=device_registry,
            session_security=session_security,
            mcp_registry=mcp_registry,
        )

        setup_state_store = SetupStateStore(selected_settings.database_path.parent / "setup-state.json")
        onboarding_service = OnboardingService(setup_state_store, doctor=doctor, authorization=authorization_service)
        provider_setup = ProviderSetup(model_registry, providers, secret_store)
        integration_setup = IntegrationSetup(integration_registry)
        permission_setup = PermissionSetup(authorization_service)
        phase13_engine = Phase13Engine(doctor, security_audit, cost_tracker, health_aggregator)

        # -- Phase 14 adaptive cognitive stack ------------------------------
        adaptive_config_data = yaml.safe_load(
            (project_root / "config" / "adaptive.yaml").read_text(encoding="utf-8")
        ) or {}
        retrieval_config = adaptive_config_data.get("retrieval", {})
        strategies_config = adaptive_config_data.get("strategies", {})
        adaptive_experience_store = ExperienceStore(
            database,
            max_retrieved=int(retrieval_config.get("max_retrieved_experiences", 5)),
            decay_half_life_days=float(retrieval_config.get("experience_decay_half_life_days", 90)),
        )
        adaptive_strategy_engine = StrategyEngine(database, AdaptiveConfig(
            minimum_strategy_sample=int(strategies_config.get("minimum_strategy_sample", 5)),
            decay_half_life_days=float(strategies_config.get("decay_half_life_days", 60)),
            regime_weight=float(strategies_config.get("regime_weight", 0.5)),
            recency_weight=float(strategies_config.get("recency_weight", 0.3)),
        ))
        adaptive_policy_engine = AdaptivePolicyEngine()
        adaptive_learner = AdaptiveLearner(
            adaptive_experience_store, adaptive_strategy_engine, improvement_engine=improvement_engine,
        )
        # Wire adaptive learner into memory manager so that user
        # corrections are actually recorded and affect future behavior.
        # Without this, record_user_correction() was dead code.
        memory_manager.adaptive_learner = adaptive_learner
        adaptive_context_service = AdaptiveContextService(
            adaptive_experience_store, task_store=task_store, goal_store=goal_store,
            automation_store=automation_store, device_registry=device_registry,
        )
        adaptive_learning_bridge = AdaptiveLearningBridge(
            event_bus, adaptive_learner, task_store,
            auto_promoter=SkillAutoPromoter(adaptive_experience_store, teachable_skills),
        )

        # -- Self-monitoring -----------------------------------------------
        from app.observability.self_monitor import SelfMonitor
        self_monitor = SelfMonitor(
            task_store=task_store,
            experience_store=adaptive_experience_store,
        )

        # -- Proactive intelligence (anticipation engine) ------------------
        from app.proactive.intelligence import ProactiveEngine as AnticipationEngine
        anticipation_engine = AnticipationEngine(
            task_store=task_store,
            experience_store=adaptive_experience_store,
        )

        # -- Meta-Learning (9 loops from Jarvis architecture) ---------------
        from app.adaptive.meta_learning import MetaLearningManager
        meta_learning = MetaLearningManager()

        # -- Trust Scoring -------------------------------------------------
        from app.memory.trust_scoring import TrustScorer
        trust_scorer = TrustScorer()

        # -- Autonomous Heartbeat Cycles -----------------------------------
        from app.adaptive.heartbeat import HeartbeatEngine
        heartbeat_engine = HeartbeatEngine(
            task_store=task_store,
            experience_store=adaptive_experience_store,
            memory_manager=memory_manager,
            meta_learning=meta_learning,
        )

        # Wire self-monitor into adaptive learner for correction tracking
        adaptive_learner.self_monitor = self_monitor

        # -- Phase 15 structured-intelligence stack -------------------------
        namespace_router = NamespaceMemoryRouter(memory_manager)
        brain_graph = BrainGraphService(
            database,
            skill_registry=skill_registry,
            agent_registry=agent_registry,
            capability_registry=capability_registry,
        )
        intelligence_engine.brain_graph = brain_graph
        # Rebuilding several years of cross-store relationships is useful
        # background work, never a reason to delay VYOM becoming ready.
        brain_graph.start_refresh()
        resolution_chain = ResolutionChain(
            memory=memory_manager,
            experience_store=adaptive_experience_store,
            skill_registry=skill_registry,
            tool_registry=tool_registry,
            capability_registry=capability_registry,
            brain_graph=brain_graph,
        )
        # Provide a real runner so the self-improvement loop can
        # actually execute git/pytest commands in an isolated branch.
        # Without this, every execute() call short-circuits to blocked.
        import asyncio as _asyncio
        async def _self_improvement_runner(command: str, cwd: Path) -> dict:
            try:
                proc = await _asyncio.create_subprocess_shell(
                    command, cwd=str(cwd),
                    stdout=_asyncio.subprocess.PIPE,
                    stderr=_asyncio.subprocess.PIPE,
                )
                stdout, stderr = await proc.communicate()
                return {
                    "ok": proc.returncode == 0,
                    "output": (stdout.decode(errors="replace") + stderr.decode(errors="replace"))[:4000],
                }
            except Exception as exc:
                return {"ok": False, "output": str(exc)[:400]}
        self_improvement = SafeSelfImprovement(
            project_root=project_root, runner=_self_improvement_runner,
        )
        universal_workbench = UniversalWorkbench(learner=adaptive_learner)
        learned_router = LearnedRouter(adaptive_learner)
        model_router.learned_router = learned_router  # evidence bias only; router stays authoritative

        async def _cognitive_emit(task, event_type, message, payload):
            await event_bus.publish(__import__("app.schemas.events", fromlist=["BrainEvent"]).BrainEvent(
                task_id=task.id if hasattr(task, "id") else str(task),
                type=event_type, human_readable_message=message, structured_payload=payload,
            ))

        cognitive_runtime = CognitiveRuntime(
            resolution_chain,
            adaptive_context_service,
            emit=_cognitive_emit,
        )
        mission_loop = MissionLoop(
            cognitive=cognitive_runtime,
            planner=ModelAssistedPlanner(model_router, providers),  # optional contract; deterministic default/fallback
            checkpoint_store=checkpoint_store,
            learner=adaptive_learner,
            emit=_cognitive_emit,
            limits=MissionLimits(),
        )

        phase13_engine.experience_store = adaptive_experience_store
        phase13_engine.policy_engine = adaptive_policy_engine

        # -- Phase 13.5 external capability intake --------------------------
        # All optional: VYOM Core boots and works with every external
        # capability disabled (regression-tested).
        external_capabilities_config = yaml.safe_load(
            selected_settings.external_capabilities_config_path.read_text(encoding="utf-8")
        ) or {}
        external_intake = ExternalCapabilityIntake(capability_registry)
        backend_router = CapabilityBackendRouter()

        defuddle_config = external_capabilities_config.get("defuddle", {})
        defuddle_enabled = bool(defuddle_config.get("enabled", True))
        async def _http_fetch(url: str) -> str:
            import httpx

            async with httpx.AsyncClient(follow_redirects=True, timeout=15.0) as client:
                response = await client.get(url)
                response.raise_for_status()
                return response.text

        async def _browser_fallback(url: str) -> object:
            from app.research.defuddle import ExtractionResult

            read = await browser_actions.perform("open", {"url": url})
            body = await browser_actions.perform("read", {"selector": "body"})
            return ExtractionResult(
                url=url, title=read.get("title", ""), content=str(body.get("text", ""))[:50_000],
                extraction_method="playwright-browser-agent", success=bool(body.get("text")),
            )

        defuddle_extractor = (
            DefuddleExtractor(fetch=_http_fetch, browser_fallback=_browser_fallback,
                              learner=adaptive_learner)
            if defuddle_enabled else None
        )
        research_task.defuddle_extractor = defuddle_extractor  # real per-source reads, bounded by BrowserSession's worker isolation
        if defuddle_enabled:
            capability_registry.register(CapabilityRecord(
                capability_id="web.extract", name="Web Page Extraction",
                description="Clean static-page extraction (Defuddle) with Playwright browser fallback",
                source=CapabilitySource.EXTERNAL, source_id="kepano/obsidian-skills:defuddle",
                tags=["research", "external", "phase13.5"],
                external=ExternalCapabilityMeta(
                    repository="kepano/obsidian-skills", version="pinned-local-implementation",
                    license="mit", trust_level="restricted",
                    intake_status=ExternalCapabilityStatus.ACTIVE,
                    benchmark={"implementation": "self-contained stdlib (no npm dependency)"},
                ),
                backends=[
                    CapabilityBackend(backend_id="defuddle", kind="external", preferred=True, health="healthy", reliability=0.8, latency_ms=400),
                    CapabilityBackend(backend_id="playwright-browser-agent", kind="browser", health="healthy", reliability=0.9, latency_ms=4000, notes="JS/login/dynamic pages"),
                ],
            ))

        codebase_memory_config = external_capabilities_config.get("codebase_memory", {})
        codebase_memory_enabled = bool(codebase_memory_config.get("enabled", True))
        codebase_memory_adapter = CodebaseMemoryAdapter(mcp_registry, selected_settings.allowed_roots) if codebase_memory_enabled else None
        if codebase_memory_enabled:
            codebase_memory_adapter.register(CodebaseMemoryTransport())  # disconnected until the user runs the server
            capability_registry.register(CapabilityRecord(
                capability_id="code.structure", name="Structural Code Understanding",
                description="Symbol/call-path/dependency queries (codebase-memory MCP) with filesystem fallback",
                source=CapabilitySource.MCP_TOOL, source_id="DeusData/codebase-memory-mcp",
                tags=["coding", "mcp", "external", "phase13.5"],
                external=ExternalCapabilityMeta(
                    repository="DeusData/codebase-memory-mcp", version="user-managed",
                    license="unknown", trust_level="restricted",
                    intake_status=ExternalCapabilityStatus.ACTIVE,
                    filesystem_access=True,
                    review_notes=["restricted to registered project roots", "filesystem fallback when down"],
                ),
                backends=[
                    CapabilityBackend(backend_id="codebase-memory-mcp", kind="mcp", preferred=True, health="unknown", reliability=0.7),
                    CapabilityBackend(backend_id="filesystem-search", kind="builtin", health="healthy", reliability=0.9, notes="always available"),
                ],
            ))

        composio_config = external_capabilities_config.get("composio", {})
        composio_enabled = bool(composio_config.get("enabled", False))
        composio_adapter = ComposioAdapter(None, secret_store) if composio_enabled else None
        runtime.phase13_engine = phase13_engine  # runtime constructed before the Phase 13 stack


        application.state.database = database
        application.state.task_store = task_store
        application.state.conversation_store = conversation_store
        application.state.curator = curator
        application.state.curator_run_store = curator_run_store
        application.state.plugin_registry = plugin_registry
        application.state.kanban_store = kanban_store
        application.state.agent_message_store = agent_message_store
        application.state.kanban_dispatcher = kanban_dispatcher
        application.state.performance_store = performance_store
        application.state.event_bus = event_bus
        application.state.progress_tracker = progress_tracker
        application.state.model_registry = model_registry
        application.state.providers = providers
        application.state.provider_health = provider_health
        application.state.quota_budgeter = quota_budgeter
        application.state.usage_tracker = usage_tracker
        application.state.tool_registry = tool_registry
        application.state.tool_executor = tool_executor
        application.state.evidence_collector = evidence_collector
        application.state.mcp_registry = mcp_registry
        application.state.mcp_manager = mcp_manager
        application.state.knowledge_service = knowledge_service
        application.state.action_engine = action_engine
        application.state.extension_bridge = extension_bridge
        application.state.extension_pairing = extension_pairing
        application.state.memory_store = memory_store
        application.state.memory_manager = memory_manager
        application.state.brain_graph = brain_graph
        application.state.embedding_provider = embedding_provider
        application.state.capability_registry = capability_registry
        application.state.capability_discovery = capability_discovery
        application.state.skill_registry = skill_registry
        application.state.learn_service = learn_service
        application.state.skill_builder = skill_builder
        application.state.skill_executor = skill_executor
        application.state.teachable_skills = teachable_skills
        application.state.agent_registry = agent_registry
        application.state.agent_factory = agent_factory
        application.state.agent_lifecycle = agent_lifecycle
        application.state.agent_runtime = agent_runtime
        application.state.multi_agent_orchestrator = multi_agent_orchestrator
        # These are wired in the adaptive stack block below.
        application.state.improvement_engine = improvement_engine
        application.state.intelligence_engine = intelligence_engine
        application.state.secret_vault = secret_vault
        application.state.integration_registry = integration_registry
        application.state.crm_store = crm_store
        application.state.email_service = email_service
        application.state.gmail_app_password_provider = app_password_provider
        application.state.calendar_service = calendar_service
        application.state.sheets_service = sheets_service
        application.state.telegram_provider = telegram_provider
        application.state.telegram_service = telegram_service
        application.state.discord_provider = discord_provider
        application.state.discord_service = discord_service
        application.state.video_service = video_service
        application.state.youtube_service = youtube_service
        application.state.instagram_service = instagram_service
        application.state.instagram_provider = instagram_provider
        application.state.facebook_service = facebook_service
        application.state.facebook_provider = facebook_provider
        application.state.twitter_service = twitter_service
        application.state.twitter_provider = twitter_provider
        application.state.linkedin_service = linkedin_service
        application.state.linkedin_provider = linkedin_provider
        application.state.meta_ads_service = meta_ads_service
        application.state.meta_ads_provider = meta_ads_provider
        application.state.whatsapp_connector = whatsapp_connector
        application.state.contact_resolver = contact_resolver
        application.state.agency_service = agency_service
        application.state.meeting_service = meeting_service
        application.state.automation_store = automation_store
        application.state.automation_scheduler = automation_scheduler
        application.state.automation_events = automation_events
        application.state.briefing_service = briefing_service
        application.state.business_engine = business_engine
        application.state.notification_service = notification_service
        application.state.research_task = research_task
        application.state.browser_session = browser_session
        application.state.browser_actions = browser_actions
        application.state.settings_database_path = selected_settings.database_path  # used by mission_packs.py's coding executor to default project_root
        application.state.discovery_engine = discovery_engine
        application.state.subscription_registry = subscription_registry
        application.state.booking_store = booking_store
        application.state.booking_search_service = booking_search_service
        application.state.booking_reservation_service = booking_reservation_service
        application.state.artifact_store = artifact_store
        application.state.artifact_engine = artifact_engine
        application.state.delivery_store = delivery_store
        application.state.client_delivery_service = client_delivery_service
        application.state.phase8_engine = phase8_engine
        application.state.window_manager = window_manager
        application.state.application_registry = application_registry
        application.state.desktop_controller = desktop_controller
        application.state.native_app_adapters = native_app_adapters
        application.state.screen_observer = screen_observer
        application.state.emergency_pause = emergency_pause
        application.state.input_safety_policy = input_safety_policy
        application.state.device_registry = device_registry
        application.state.device_pairing = device_pairing
        application.state.device_heartbeat = device_heartbeat
        application.state.phase9_engine = phase9_engine
        application.state.market_data_registry = market_data_registry
        application.state.quote_service = quote_service
        application.state.candle_service = candle_service
        application.state.fundamentals_service = fundamentals_service
        application.state.market_researcher = market_researcher
        application.state.portfolio_store = portfolio_store
        application.state.watchlist_store = watchlist_store
        application.state.portfolio_service = portfolio_service
        application.state.risk_rules = risk_rules
        application.state.risk_kill_switch = risk_kill_switch
        application.state.risk_engine = risk_engine
        application.state.paper_kill_switch = paper_kill_switch
        application.state.paper_order_store = paper_order_store
        application.state.paper_broker = paper_broker
        application.state.trade_manager = trade_manager
        application.state.journal_store = journal_store
        application.state.journal_service = journal_service
        application.state.strategy_registry = strategy_registry
        application.state.backtest_engine = backtest_engine
        application.state.alert_store = alert_store
        application.state.alert_engine = alert_engine
        application.state.phase10_engine = phase10_engine
        application.state.personal_profile_service = personal_profile_service
        application.state.commitment_service = commitment_service
        application.state.goal_store = goal_store
        application.state.goal_manager = goal_manager
        application.state.goal_evaluator = goal_evaluator
        application.state.milestone_service = milestone_service
        application.state.habit_store = habit_store
        application.state.habit_event_store = habit_event_store
        application.state.habit_tracker = habit_tracker
        application.state.habit_insight_service = habit_insight_service
        application.state.routine_store = routine_store
        application.state.routine_manager = routine_manager
        application.state.routine_completion_service = routine_completion_service
        application.state.routine_scheduler = routine_scheduler
        application.state.routine_adaptation_service = routine_adaptation_service
        application.state.focus_session_service = focus_session_service
        application.state.workload_calculator = workload_calculator
        application.state.chief_of_staff_orchestrator = chief_of_staff_orchestrator
        application.state.proactive_rules = proactive_rules
        application.state.proactive_engine = proactive_engine
        application.state.quiet_mode = quiet_mode
        application.state.notification_delivery_service = notification_delivery_service
        application.state.notification_preferences_service = notification_preferences_service
        application.state.phase11_engine = phase11_engine
        application.state.phase13_engine = phase13_engine
        application.state.coordinator = coordinator
        application.state.node_store = node_store
        application.state.token_store = token_store
        application.state.lease_manager = lease_manager
        application.state.distributed_audit = distributed_audit
        application.state.budget_manager = budget_manager
        application.state.ownership_registry = ownership_registry
        application.state.node_router = node_router
        application.state.checkpoint_store = checkpoint_store
        application.state.task_dispatcher = task_dispatcher
        application.state.task_handoff_service = task_handoff_service
        application.state.sync_journal = sync_journal
        application.state.sync_engine = sync_engine
        application.state.offline_queue = offline_queue
        application.state.replication_manager = replication_manager
        application.state.health_aggregator = health_aggregator
        application.state.reliability_metrics = reliability_metrics
        application.state.circuit_breakers = circuit_breakers
        application.state.watchdog = watchdog
        application.state.recovery_service = recovery_service
        application.state.remote_sessions = remote_sessions
        application.state.remote_command_gateway = remote_command_gateway
        application.state.remote_approvals = remote_approvals
        application.state.remote_notification_router = remote_notification_router
        application.state.remote_delivery_store = remote_delivery_store
        application.state.remote_delivery_bridge = remote_delivery_bridge
        application.state.backup_manager = backup_manager
        application.state.restore_service = restore_service
        application.state.activity_summary = activity_summary
        application.state.supervisor = supervisor
        application.state.runtime = runtime
        # -- Phase 13 state --------------------------------------------------
        application.state.secret_store = secret_store
        application.state.credential_manager = credential_manager
        application.state.session_security = session_security
        application.state.authorization_service = authorization_service
        application.state.global_rate_limits = global_rate_limits
        application.state.security_events = security_events
        application.state.structured_logging = structured_logging
        application.state.metrics_registry = metrics_registry
        application.state.tracer = tracer
        application.state.performance_monitor = performance_monitor
        application.state.cost_tracker = cost_tracker
        application.state.crash_reporter = crash_reporter
        application.state.migration_manager = migration_manager
        application.state.config_validator = config_validator
        application.state.startup_checks = startup_checks
        application.state.readiness = readiness_tracker
        application.state.doctor = doctor
        application.state.security_audit = security_audit
        application.state.setup_state_store = setup_state_store
        application.state.onboarding = onboarding_service
        application.state.provider_setup = provider_setup
        application.state.integration_setup = integration_setup
        application.state.permission_setup = permission_setup
        application.state.release_channel = str(release_config.get("channel", "alpha"))
        application.state.adaptive_experience_store = adaptive_experience_store
        application.state.adaptive_strategy_engine = adaptive_strategy_engine
        application.state.adaptive_policy_engine = adaptive_policy_engine
        application.state.adaptive_learner = adaptive_learner
        application.state.adaptive_context_service = adaptive_context_service
        application.state.external_intake = external_intake
        application.state.capability_backend_router = backend_router
        application.state.defuddle_extractor = defuddle_extractor
        application.state.codebase_memory_adapter = codebase_memory_adapter
        application.state.composio_adapter = composio_adapter
        application.state.namespace_router = namespace_router
        application.state.resolution_chain = resolution_chain
        application.state.self_improvement = self_improvement
        application.state.self_monitor = self_monitor
        application.state.anticipation_engine = anticipation_engine
        application.state.meta_learning = meta_learning
        application.state.trust_scorer = trust_scorer
        application.state.heartbeat_engine = heartbeat_engine
        application.state.universal_workbench = universal_workbench
        application.state.learned_router = learned_router
        application.state.cognitive_runtime = cognitive_runtime
        application.state.mission_loop = mission_loop
        application.state.mission_packs = MISSION_PACKS
        application.state.run_mission_pack = run_pack
        application.state.improvement_metrics = ImprovementMetrics(
            adaptive_experience_store, adaptive_strategy_engine
        )
        runtime.adaptive_context_service = adaptive_context_service  # planner context source
        runtime.cognitive_runtime = cognitive_runtime
        runtime.mission_loop = mission_loop
        # Unrecognised goals plan over the LIVE tool registry instead of
        # falling through to a text-only model answer.
        # One shared ProviderHealth across the router, the task runtime and
        # the general planner, so a single 429 stops every caller instead
        # of each discovering the rate limit independently.
        runtime.general_planner = GeneralPlanner(model_router, providers, provider_health=provider_health)
        # A multi-domain goal is split across the role agents; a
        # single-domain goal keeps the cheaper single planner above.
        runtime.multi_agent_orchestrator = multi_agent_orchestrator
        multi_agent_orchestrator.task_runtime = runtime
        # Live "where has the work reached" board - read by
        # _answer_runtime_introspection so "kaam kaha pahuncha?" names the
        # agent and step, not just "executing".
        runtime.progress_tracker = progress_tracker
        # The soul fix: unrecognised natural language gets ONE cheap
        # structured model call (action vs conversation, tone, urgency)
        # before any word-count heuristic decides it is small talk.
        runtime.llm_triage = LLMTriage(model_router, providers)
        runtime.memory_retriever = MemoryRetriever(memory_store, embedding_provider)
        runtime.memory_store = memory_store
        runtime.memory_manager = memory_manager
        runtime.knowledge_service = knowledge_service
        runtime.automation_store = automation_store
        runtime.conversation_store = conversation_store
        runtime.plugin_registry = plugin_registry
        runtime.learn_service = learn_service

        async def _mcp_connector(service_name: str) -> dict:
            """Wires the classifier's chat-native 'connect to X mcp'
            intent to the SAME lookup POST /api/mcp/connect already
            uses (app/api/mcp.py connect_service) - a FastAPI app
            instance exposes `.state` identically to `request.app.state`,
            so no fake Request object or duplicated matching logic is
            needed here."""
            from app.api.mcp import ConnectServiceRequest, connect_service

            return await connect_service(ConnectServiceRequest(service=service_name), application)

        runtime.mcp_connector = _mcp_connector
        # Phase 12 crash recovery runs BEFORE any task is restarted: a
        # consequential task with evidence of a partial external action
        # (or one owned by another node) must never be blindly
        # re-executed just because the process restarted. Recovery
        # decides resume/retry/pause/needs_review first; only tasks it
        # actually clears (RESUME/RETRY) get restarted below - everything
        # else is parked as PAUSED for explicit review, not silently
        # re-run.
        recovery_decisions = await recovery_service.recover()
        _boot_step("crash-recovery")
        application.state.last_recovery_decisions = [
            decision.model_dump() for decision in recovery_decisions
        ]
        not_safe_to_restart = {
            decision.task_id for decision in recovery_decisions
            if decision.action not in (RecoveryAction.RESUME, RecoveryAction.RETRY)
        }
        await runtime.resume_incomplete_tasks(skip_ids=not_safe_to_restart)
        _boot_step("resume-incomplete-tasks")
        # Phase 13 production startup validation: configuration, database,
        # migrations, secret store, directories. Degraded mode is allowed
        # when the failures are optional; hard failures mark not-ready.
        # Connect every configured MCP server now, after every built-in
        # tool/skill/capability is already wired, so a slow or failing
        # server can never delay them and its tools land in the registry
        # before the readiness check runs.
        # Connect every configured MCP server AFTER the server starts
        # serving: these are external network sessions (measured at 19.2s
        # on an ordinary boot - the single largest slice of the ~95s cold
        # start the desktop app sat through as "Brain disconnected"), and
        # every built-in tool/skill/capability is already wired above. A
        # slow or failing MCP server must never hold /health hostage;
        # its tools land in the registry seconds later.
        async def _connect_mcp_after_boot() -> None:
            try:
                results = await mcp_manager.connect_all(configured_mcp_servers)
            except Exception as error:  # a failing connector never blocks boot
                _boot_logger.warning("mcp background connect failed: %s", error)
                return
            for outcome in results:
                if outcome.get("status") != "connected":
                    startup_warnings = getattr(application.state, "mcp_startup_warnings", [])
                    startup_warnings.append(outcome)
                    application.state.mcp_startup_warnings = startup_warnings

        mcp_boot_task = asyncio.create_task(_connect_mcp_after_boot())

        startup_report = await startup_checks.run()
        _boot_step("startup-checks")
        application.state.startup_report = startup_report
        if startup_report.ready:
            readiness_tracker.mark_ready()
        elif startup_report.ok:
            readiness_tracker.mark_degraded(startup_report.warnings)
        else:
            readiness_tracker.mark_degraded(startup_report.failures)
        automation_scheduler.start()
        automation_events.start()
        curator.start()
        kanban_dispatcher.start()
        remote_delivery_bridge.start()
        supervisor.start()
        await sync_bridge.start()
        adaptive_learning_bridge.start()
        # Phone control with a FREE bot token (BotFather), dormant until
        # TELEGRAM_BOT_TOKEN is set — no paid API, no extra dependency.
        # A bot token authenticates VYOM to Telegram; it does not identify the owner.
        # Remote command intake stays off until the local owner explicitly allowlists a chat id.
        telegram_gateway = None
        telegram_allowed_chat_ids = {
            item.strip()
            for item in os.getenv("VYOM_TELEGRAM_OWNER_CHAT_IDS", "").replace(";", ",").split(",")
            if item.strip()
        }
        if telegram_bot_token and telegram_allowed_chat_ids:
            from app.gateway.telegram import TelegramGateway

            telegram_gateway = TelegramGateway(
                telegram_bot_token, runtime, task_store, data_dir / "telegram-state.json",
                allowed_chat_ids=telegram_allowed_chat_ids,
                allowed_file_roots=[settings.artifacts_root],
            )
            await telegram_gateway.start()
        application.state.telegram_gateway = telegram_gateway
        _boot_step("engines-and-bridges")
        _boot_logger.info("boot.total lifespan init complete in %.2fs", _time.perf_counter() - _boot_t0)
        yield
        # The deferred MCP connector from boot must not race the shutdown
        # path that disconnects those same servers below.
        mcp_boot_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await mcp_boot_task
        if telegram_gateway is not None:
            await telegram_gateway.stop()
        await adaptive_learning_bridge.stop()
        await sync_bridge.stop()
        await supervisor.stop()
        await automation_events.stop()
        await remote_delivery_bridge.stop()
        await automation_scheduler.stop()
        await curator.stop()
        await kanban_dispatcher.stop()
        for active in tuple(runtime.active.values()):
            active.cancel()
        if runtime.active:
            await asyncio.gather(*runtime.active.values(), return_exceptions=True)
        await action_engine.shutdown()
        for server_id in list(mcp_registry.servers):
            await mcp_manager.disconnect(server_id)
        await browser_session.shutdown()
        # Release pooled provider HTTP connections cleanly.
        for provider in tuple(providers.providers.values()):
            closer = getattr(provider, "aclose", None)
            if closer is not None:
                with contextlib.suppress(Exception):
                    await closer()
        await brain_graph.close()
        await database.close()

    application = FastAPI(
        title="VYOM Brain",
        version="0.1.0",
        lifespan=lifespan,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:1420", "http://127.0.0.1:1420",
            # Packaged Tauri origins. Windows serves the RELEASE build from
            # http://tauri.localhost - its absence here meant every Brain
            # call from the installed app failed CORS while the dev build
            # (http://localhost:1420) worked, which is exactly why VYOM
            # showed "Brain disconnected" only outside development.
            "tauri://localhost", "https://tauri.localhost", "http://tauri.localhost",
        ],
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type"],
    )
    application.add_middleware(ProductionMiddleware)
    application.include_router(tasks.router)
    application.include_router(conversation_api.router)
    application.include_router(curator_api.router)
    application.include_router(plugins_api.router)
    application.include_router(kanban_api.router)
    application.include_router(learn_api.router)
    application.include_router(approvals.router)
    application.include_router(models.router)
    application.include_router(tools.router)
    application.include_router(mcp_api.router)
    application.include_router(knowledge_api.router)
    application.include_router(adaptive_api.router)
    application.include_router(sheets_api.router)
    application.include_router(telegram_api.router)
    application.include_router(discord_api.router)
    application.include_router(video_api.router)
    application.include_router(youtube_api.router)
    application.include_router(instagram_api.router)
    application.include_router(facebook_api.router)
    application.include_router(twitter_api.router)
    application.include_router(linkedin_api.router)
    application.include_router(meta_ads_api.router)
    application.include_router(whatsapp_api.router)
    application.include_router(search_api.router)
    application.include_router(memory.router)
    from app.api import memory_viz
    application.include_router(memory_viz.router)
    application.include_router(brain_graph_api.router)
    application.include_router(skills.router)
    application.include_router(agents.router)
    application.include_router(capabilities.router)
    application.include_router(integrations.router)
    application.include_router(email_api.router)
    application.include_router(calendar_api.router)
    application.include_router(contacts.router)
    application.include_router(extension_api.router)
    application.include_router(crm.router)
    application.include_router(agency.router)
    application.include_router(meetings.router)
    application.include_router(automations.router)
    application.include_router(research_api.router)
    application.include_router(discovery_api.router)
    application.include_router(booking_api.router)
    application.include_router(artifacts_api.router)
    application.include_router(delivery_api.router)
    application.include_router(desktop_api.router)
    application.include_router(screen_api.router)
    application.include_router(devices_api.router)
    application.include_router(finance_api.router)
    application.include_router(markets_api.router)
    application.include_router(paper_trading_api.router)
    application.include_router(backtesting_api.router)
    application.include_router(alerts_api.router)
    application.include_router(personal_api.router)
    application.include_router(goals_api.router)
    application.include_router(habits_api.router)
    application.include_router(routines_api.router)
    application.include_router(reviews_api.router)
    application.include_router(nodes_api.router)
    application.include_router(sync_api.router)
    application.include_router(remote_api.router)
    application.include_router(health_api.router)
    application.include_router(backup_api.router)
    application.include_router(production_api.router)
    application.include_router(diagnostics_api.router)
    application.include_router(setup_api.router)
    application.include_router(observability_api.router)
    application.include_router(quota.router)
    from app.api import persona as persona_api, ecosystem as ecosystem_api
    application.include_router(persona_api.router)
    application.include_router(ecosystem_api.router)
    application.include_router(websocket.router)

    @application.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": "vyom-brain"}

    @application.get("/healthz")
    async def healthz() -> dict[str, bool]:
        return {"alive": True}

    @application.get("/readyz")
    async def readyz(request: Request) -> dict:
        snapshot = request.app.state.readiness.snapshot()
        if not snapshot.get("alive", False):
            raise HTTPException(status_code=503, detail=snapshot)
        if not snapshot.get("ready", False):
            raise HTTPException(status_code=503, detail=snapshot)
        return snapshot

    return application


configure_logging()
app = create_app()


if __name__ == "__main__":
    settings = get_settings()
    uvicorn.run("app.main:app", host=settings.host, port=settings.port, reload=False)
