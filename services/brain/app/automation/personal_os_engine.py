from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Awaitable, Callable
from uuid import uuid4

from app.artifacts.diagram_engine import DiagramEdge, DiagramEngine, DiagramNode, DiagramSpec, DiagramType
from app.artifacts.engine import ArtifactEngine
from app.artifacts.presentation_builder import PresentationBuilder
from app.artifacts.report_builder import ReportBuilder
from app.artifacts.schemas import ArtifactSpec, ArtifactType
from app.booking.comparator import BookingComparator
from app.booking.planner import BookingPlanner
from app.booking.reservation import BookingReservationService, DuplicateBookingError
from app.booking.schemas import BookingCategory, BookingConstraints, BookingStatus
from app.booking.search import BookingSearchService
from app.booking.verifier import BookingVerifier
from app.crm.store import CRMStore
from app.delivery.client_delivery import ClientDeliveryService
from app.delivery.package_builder import PackageBuilder
from app.delivery.quality_gate import QualityGate
from app.discovery.engine import DiscoveryEngine
from app.persistence.database import Database
from app.research.orchestrator import DeepResearchTask
from app.research.schemas import ResearchDepth
from app.schemas.results import ExecutionResult
from app.schemas.tasks import Task, TaskProfile

from .extraction import (
    extract_booking_category,
    extract_client_name,
    extract_date,
    extract_party_size,
    extract_research_topic,
    extract_time,
)

EventEmitter = Callable[[str, str, dict], Awaitable[None]]


async def _noop_emit(event_type: str, message: str, payload: dict) -> None:
    pass

RESEARCH_TRIGGERS = (
    "research the top competitors for", "research competitors for", "research ",
    "does vyom have something that can do", "find a tool for", "find a cheap tool for",
)


def _frame(x: float, y: float, width: float, layer: int | None = None) -> dict:
    frame = {"x": x, "y": y, "width": width}
    if layer:
        frame["layer"] = layer
    return frame


def _composition(identifier: str, mode: str, label: str, summary: str, objects: list[dict]) -> dict:
    states = ["Understanding", "Researching", "Executing", "Verifying", "Completed"]
    sequence = []
    for index, item in enumerate(objects):
        sequence.append({
            "id": f"reveal-{index}", "label": item.get("eyebrow", item["title"]),
            "atMs": index * 320, "state": states[min(index, len(states) - 1)], "objectIds": [item["id"]],
        })
    return {
        "schemaVersion": 1, "id": identifier, "mode": mode, "label": label,
        "summary": summary, "generatedAt": datetime.now(timezone.utc).isoformat(),
        "objects": objects, "sequence": sequence,
    }


class PersonalOSEngine:
    """The advanced automation, research, booking and client delivery engine for VYOM."""

    INTENTS = {
        "deep_research", "competitor_research", "tool_discovery", "mcp_discovery",
        "booking_search", "booking_reserve", "generate_client_report",
        "generate_presentation", "prepare_client_delivery", "generate_content_plan",
    }

    def __init__(
        self,
        research_task: DeepResearchTask,
        discovery_engine: DiscoveryEngine,
        booking_search: BookingSearchService,
        booking_reservation: BookingReservationService,
        artifact_engine: ArtifactEngine,
        delivery_service: ClientDeliveryService,
        crm_store: CRMStore,
    ) -> None:
        self.research_task = research_task
        self.discovery_engine = discovery_engine
        self.booking_planner = BookingPlanner()
        self.booking_search = booking_search
        self.booking_comparator = BookingComparator()
        self.booking_reservation = booking_reservation
        self.booking_verifier = BookingVerifier()
        self.artifact_engine = artifact_engine
        self.report_builder = ReportBuilder()
        self.presentation_builder = PresentationBuilder()
        self.delivery_service = delivery_service
        self.package_builder = PackageBuilder()
        self.quality_gate = QualityGate()
        self.crm_store = crm_store
        self._last_booking_constraints: dict[str, BookingConstraints] = {}
        self._last_booking_category: dict[str, BookingCategory] = {}
        self.synthesis_provider = None
        self.synthesis_model: str | None = None

    @classmethod
    def create_default(
        cls,
        database: Database,
        artifacts_root: Path | None = None,
        research_config: dict | None = None,
    ) -> "PersonalOSEngine":
        """Standalone factory to instantiate PersonalOSEngine with all real sub-services."""
        from app.artifacts.export_manager import ArtifactStore
        from app.booking.store import BookingStore
        from app.delivery.client_delivery import DeliveryStore
        from app.discovery.saas_discovery import SubscriptionRegistry
        from app.capabilities.registry import CapabilityRegistry
        from app.mcp.registry import MCPRegistry

        research_config = research_config or {"search_providers": {"local_fixture": {"enabled": True}}}
        research_task = DeepResearchTask.from_config(research_config)
        cap_reg = CapabilityRegistry()
        sub_reg = SubscriptionRegistry()
        mcp_reg = MCPRegistry()
        discovery_engine = DiscoveryEngine(cap_reg, research_task, sub_reg, mcp_reg)

        booking_store = BookingStore(database)
        booking_search = BookingSearchService({})
        booking_reservation = BookingReservationService(booking_search, booking_store)

        artifacts_path = artifacts_root or (Path("services/brain/data/artifacts") if Path("services/brain").exists() else Path("data/artifacts"))
        artifact_store = ArtifactStore(database)
        artifact_engine = ArtifactEngine(artifacts_path, artifact_store)

        delivery_store = DeliveryStore(database)
        delivery_service = ClientDeliveryService(delivery_store)
        crm_store = CRMStore(database)

        return cls(
            research_task=research_task,
            discovery_engine=discovery_engine,
            booking_search=booking_search,
            booking_reservation=booking_reservation,
            artifact_engine=artifact_engine,
            delivery_service=delivery_service,
            crm_store=crm_store,
        )

    # -- Direct Python Automation API ---------------------------------

    async def run_deep_research(self, topic: str, depth: ResearchDepth = ResearchDepth.STANDARD, emit: EventEmitter | None = None) -> ExecutionResult:
        """Run deep multi-source research for any topic directly from Python."""
        task = Task(id=f"auto_research_{uuid4().hex[:8]}", user_request=f"research {topic}", goal=f"research {topic}")
        profile = TaskProfile(intent="deep_research", summary=f"Research: {topic}")
        return await self.execute(task, profile, emit or _noop_emit)

    async def discover_tools(self, need: str, emit: EventEmitter | None = None) -> ExecutionResult:
        """Discover tools, APIs, or MCP servers for a given need."""
        task = Task(id=f"auto_discover_{uuid4().hex[:8]}", user_request=f"find a tool for {need}", goal=f"find a tool for {need}")
        profile = TaskProfile(intent="tool_discovery", summary=f"Discover: {need}")
        return await self.execute(task, profile, emit or _noop_emit)

    async def search_bookings(self, category: str = "restaurant", date: str | None = None, time: str | None = None, party_size: int | None = None, emit: EventEmitter | None = None) -> ExecutionResult:
        """Search and rank booking options under constraints."""
        req = f"book a {category}"
        if party_size:
            req += f" for {party_size} people"
        if date:
            req += f" on {date}"
        if time:
            req += f" at {time}"
        task = Task(id=f"auto_book_{uuid4().hex[:8]}", user_request=req, goal=req)
        profile = TaskProfile(intent="booking_search", summary=f"Book: {category}")
        return await self.execute(task, profile, emit or _noop_emit)

    async def generate_client_report(self, client: str, emit: EventEmitter | None = None) -> ExecutionResult:
        """Generate a verified markdown client report from persistent CRM state."""
        task = Task(id=f"auto_report_{uuid4().hex[:8]}", user_request=f"generate client report for {client}", goal=f"generate client report for {client}")
        profile = TaskProfile(intent="generate_client_report", summary=f"Report: {client}")
        return await self.execute(task, profile, emit or _noop_emit)

    async def prepare_client_delivery(self, client: str, emit: EventEmitter | None = None) -> ExecutionResult:
        """Prepare a client delivery package through the Quality Gate."""
        task = Task(id=f"auto_delivery_{uuid4().hex[:8]}", user_request=f"prepare client delivery for {client}", goal=f"prepare client delivery for {client}")
        profile = TaskProfile(intent="prepare_client_delivery", summary=f"Delivery: {client}")
        return await self.execute(task, profile, emit or _noop_emit)

    async def create_custom_spreadsheet(
        self,
        filename: str,
        headers: list[str],
        rows: list[list[Any]],
        *,
        sheet_name: str = "Sheet1",
        as_csv: bool = False,
    ) -> ExecutionResult:
        """Create a custom Excel (.xlsx) or CSV spreadsheet strictly as requested by owner."""
        from app.sheets.local_excel import get_local_excel_service
        svc = get_local_excel_service()
        file_path = svc.create_spreadsheet(filename, headers, rows, sheet_name=sheet_name, as_csv=as_csv)
        statement = f"Spreadsheet '{file_path.name}' created with {len(headers)} columns and {len(rows)} row(s)."
        return ExecutionResult(
            response=statement,
            structured_data={
                "file_path": str(file_path),
                "headers": headers,
                "row_count": len(rows),
                "format": "csv" if as_csv else "xlsx",
            },
            evidence=[f"file_exists:{file_path.exists()}", f"file_size:{file_path.stat().st_size}B"],
        )

    async def export_leads_to_excel(self, filename: str = "leads_export.xlsx") -> ExecutionResult:
        """Export all persistent CRM leads into a formatted Excel spreadsheet."""
        leads = await self.crm_store.leads()
        headers = ["ID", "Company", "State", "Score", "Domain", "Created At"]
        rows = [
            [lead.id, lead.company or lead.name, lead.state.value, lead.score, lead.domain or "-", lead.created_at.strftime("%Y-%m-%d")]
            for lead in leads
        ]
        return await self.create_custom_spreadsheet(filename, headers, rows, sheet_name="Leads")

    def supports(self, intent: str) -> bool:
        return intent in self.INTENTS

    async def execute(self, task: Task, profile: TaskProfile, emit: EventEmitter) -> ExecutionResult:
        intent = profile.intent
        if intent in {"deep_research", "competitor_research"}:
            return await self._deep_research(task, emit)
        if intent == "tool_discovery":
            return await self._tool_discovery(task, emit)
        if intent == "mcp_discovery":
            return await self._mcp_discovery(task, emit)
        if intent == "booking_search":
            return await self._booking_search(task, emit)
        if intent == "booking_reserve":
            return await self._booking_reserve(task, emit)
        if intent == "generate_client_report":
            return await self._generate_client_report(task, emit)
        if intent == "generate_presentation":
            return await self._generate_presentation(task, emit)
        if intent == "prepare_client_delivery":
            return await self._prepare_client_delivery(task, emit)
        if intent == "generate_content_plan":
            return await self._generate_content_plan(task, emit)
        raise RuntimeError(f"Unsupported Personal OS intent: {intent}")

    async def _generate_content_plan(self, task: Task, emit: EventEmitter) -> ExecutionResult:
        from app.agency.content_ops import get_viral_content_engine
        engine = get_viral_content_engine()
        req = task.user_request.lower()

        # Match target account from request
        target_account = "gunjan_ai_tech"
        if "fitness" in req or "calisthenics" in req or "gym" in req:
            target_account = "gunjan_fitness"
        elif "finance" in req or "trading" in req or "stock" in req:
            target_account = "gunjan_finance"
        elif "lifestyle" in req or "mindset" in req:
            target_account = "gunjan_lifestyle"
        else:
            # Check custom client registered
            for acc in engine.workspaces.list_accounts():
                if acc.account_id in req or acc.owner_name.lower() in req or acc.handle.lower() in req:
                    target_account = acc.account_id
                    break

        await emit("content_plan_started", f"Generating 30-day viral content plan for {target_account}", {"account": target_account})
        plan = engine.generate_30day_content_plan(target_account)
        await emit("content_plan_ready", f"30-day plan created with Excel deliverable at {plan['excel_file']}", {"excel": plan['excel_file']})

        statement = (
            f"30-Day Content Plan ready for {plan['handle']} ({plan['niche']}). "
            f"Delivered in formatted Excel: '{Path(plan['excel_file']).name}' and Markdown calendar."
        )
        return ExecutionResult(
            response=statement,
            structured_data=plan,
            evidence=[f"excel_exists:{Path(plan['excel_file']).exists()}", f"account:{target_account}"],
        )

    # -- Research -----------------------------------------------------

    async def _deep_research(self, task: Task, emit: EventEmitter) -> ExecutionResult:
        topic = extract_research_topic(task.user_request, RESEARCH_TRIGGERS)
        depth = ResearchDepth.DEEP if "competitor" in task.user_request.lower() else ResearchDepth.STANDARD
        required_facts = ["pricing", "key features", "market positioning"] if "competitor" in task.user_request.lower() else None

        async def research_emit(event_type: str, message: str, payload: dict) -> None:
            await emit(event_type, message, payload)

        result = await self.research_task.run(
            topic, depth=depth, required_facts=required_facts, emit=research_emit,
            synthesis_provider=self.synthesis_provider,
            synthesis_model=self.synthesis_model,
        )

        source_nodes = [
            {"id": source.source_id, "label": source.title[:40], "type": source.source_type.value, "confidence": source.trust_score}
            for source in result.sources
        ]
        objects = [
            {
                "id": "research-map", "type": "research-map", "title": f"Research map: {topic}",
                "eyebrow": f"{len(result.sources)} source(s), {result.plan.depth.value} depth",
                "tone": "intelligence", "frame": _frame(4, 12, 44),
                "nodes": source_nodes, "goal": topic,
            },
            {
                "id": "confidence", "type": "confidence-indicator", "title": "Research confidence",
                "eyebrow": result.verification_state.value, "tone": "verified" if result.verification_state.value == "verified" else "attention",
                "frame": _frame(52, 12, 20), "score": result.confidence, "label": result.verification_state.value,
            },
            {
                "id": "evidence", "type": "evidence-card-group", "title": "Evidence",
                "eyebrow": "Traceable citations", "frame": _frame(4, 56, 44),
                "cards": [{"statement": claim.statement[:140], "confidence": claim.confidence, "sources": claim.supporting_sources} for claim in result.claims[:6]],
            },
        ]
        if result.contradictions:
            objects.append({
                "id": "contradictions", "type": "contradiction-panel", "title": "Disagreements between sources",
                "eyebrow": f"{len(result.contradictions)} found", "tone": "attention", "frame": _frame(52, 40, 44),
                "items": [
                    {"claim": item.claim, "difference": item.difference, "recommendedInterpretation": item.recommended_interpretation}
                    for item in result.contradictions
                ],
            })
        composition = _composition(f"research-{task.id}", "brain-context", f"Research: {topic}", result.synthesis, objects)
        return ExecutionResult(
            response=result.synthesis, structured_data=result.model_dump(mode="json"),
            ui_composition=composition, evidence=result.citations,
        )

    # -- Discovery ------------------------------------------------------

    async def _tool_discovery(self, task: Task, emit: EventEmitter) -> ExecutionResult:
        need = extract_research_topic(task.user_request, ("find a tool/api that can", "find a cheap tool/api that can", "find a tool for", "compare tools for", "find the best tool for"))

        async def discovery_emit(event_type: str, message: str, payload: dict) -> None:
            await emit(event_type, message, payload)

        recommendation = await self.discovery_engine.discover(need, emit=discovery_emit)
        objects = [{
            "id": "recommendation", "type": "verified-result", "title": "Discovery recommendation",
            "eyebrow": "Capability -> subscription -> research", "tone": "verified", "frame": _frame(10, 14, 40),
            "statement": recommendation.recommendation,
            "evidence": [f"gap_detected:{not recommendation.gap_report.has_existing_capability}"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }]
        if recommendation.saas_candidates:
            objects.append({
                "id": "comparison", "type": "comparison-table", "title": "Researched options", "eyebrow": "Compared, not auto-subscribed",
                "tone": "intelligence", "frame": _frame(54, 14, 40),
                "headers": ["Candidate", "Score", "Reasons"],
                "rows": [[item.candidate, item.score, "; ".join(item.reasons)] for item in recommendation.saas_candidates[:5]],
            })
        composition = _composition(f"discovery-{task.id}", "brain-context", "Tool discovery", recommendation.recommendation, objects)
        return ExecutionResult(
            response=recommendation.recommendation,
            structured_data={"has_existing_capability": recommendation.gap_report.has_existing_capability, "has_existing_subscription": bool(recommendation.existing_subscription)},
            ui_composition=composition,
            evidence=[f"need:{need}"],
        )

    async def _mcp_discovery(self, task: Task, emit: EventEmitter) -> ExecutionResult:
        need = extract_research_topic(task.user_request, ("can vyom connect to",))

        async def discovery_emit(event_type: str, message: str, payload: dict) -> None:
            await emit(event_type, message, payload)

        recommendation = await self.discovery_engine.discover(need, emit=discovery_emit)
        rows = [[candidate.name, candidate.trust, ", ".join(candidate.risks) or "none listed"] for candidate in recommendation.mcp_candidates]
        objects = [{
            "id": "mcp-options", "type": "comparison-table", "title": f"MCP candidates for {need}",
            "eyebrow": "Restricted trust · approval required before connection", "tone": "attention" if rows else "neutral",
            "frame": _frame(8, 16, 52), "headers": ["Server", "Trust", "Risks"], "rows": rows or [["No candidate found", "-", "-"]],
        }]
        composition = _composition(f"mcp-{task.id}", "brain-context", "MCP discovery", recommendation.recommendation, objects)
        return ExecutionResult(
            response=recommendation.recommendation, structured_data={"candidates": [candidate.model_dump(mode="json") for candidate in recommendation.mcp_candidates]},
            ui_composition=composition, evidence=[f"need:{need}"],
        )

    # -- Booking ----------------------------------------------------------

    async def _booking_search(self, task: Task, emit: EventEmitter) -> ExecutionResult:
        category_value = extract_booking_category(task.user_request) or "restaurant"
        category = BookingCategory(category_value)
        constraints = BookingConstraints(
            date=extract_date(task.user_request),
            time=extract_time(task.user_request),
            party_size=extract_party_size(task.user_request),
        )
        request = self.booking_planner.plan(category, constraints, task_id=task.id)
        self._last_booking_constraints[task.id] = constraints
        self._last_booking_category[task.id] = category

        await emit("booking_search_started", f"Searching {category.value} options", {"category": category.value})
        try:
            options = await self.booking_search.search(category.value, constraints)
        except RuntimeError as error:
            statement = f"Booking search unavailable: {error}"
            obj = {"id": "unavailable", "type": "verified-result", "title": "Booking", "eyebrow": "Capability unavailable", "tone": "attention", "frame": _frame(20, 20, 46), "statement": statement, "evidence": [f"category:{category.value}"], "timestamp": datetime.now(timezone.utc).isoformat()}
            return ExecutionResult(response=statement, structured_data={"available": False}, ui_composition=_composition(f"booking-{task.id}", "brain-context", "Booking", statement, [obj]), evidence=[])

        ranked = self.booking_comparator.rank(options, constraints)
        for option in ranked:
            await emit("booking_option_found", option.name, {"option_id": option.option_id, "price": option.price})
        exact = self.booking_comparator.exact_matches(ranked)
        alternatives = self.booking_comparator.alternatives(ranked)

        objects = [{
            "id": "options", "type": "comparison-table", "title": f"{category.value.title()} options", "eyebrow": f"{len(exact)} exact match(es), {len(alternatives)} alternative(s)",
            "tone": "intelligence", "frame": _frame(8, 14, 52),
            "headers": ["Option", "Price", "Rating", "Matches constraints"],
            "rows": [[option.name, f"{option.price} {option.currency}" if option.price else "n/a", option.rating or "n/a", "yes" if option.matches_constraints else f"no ({', '.join(option.relaxed_constraints)})"] for option in ranked[:5]],
        }]
        if ranked:
            objects.append({
                "id": "recommendation", "type": "verified-result", "title": "Recommendation", "eyebrow": "Top ranked option", "tone": "verified",
                "frame": _frame(62, 14, 32), "statement": f"{ranked[0].name} best matches your constraints. Reservation requires explicit approval before booking.",
                "evidence": [f"option_id:{ranked[0].option_id}"], "timestamp": datetime.now(timezone.utc).isoformat(),
            })
        summary = f"Found {len(ranked)} option(s); reservation is a separate approved step."
        composition = _composition(f"booking-{task.id}", "brain-context", "Booking search", summary, objects)
        return ExecutionResult(
            response=summary, structured_data={"options": [option.model_dump(mode="json") for option in ranked], "request_id": request.id},
            ui_composition=composition, evidence=[f"options_found:{len(ranked)}"],
        )

    async def _booking_reserve(self, task: Task, emit: EventEmitter) -> ExecutionResult:
        category = self._last_booking_category.get(task.id) or BookingCategory.RESTAURANT
        constraints = self._last_booking_constraints.get(task.id) or BookingConstraints()
        request = self.booking_planner.plan(category, constraints, task_id=task.id)

        try:
            options = await self.booking_search.search(category.value, constraints)
        except RuntimeError as error:
            statement = f"Booking unavailable: {error}"
            obj = {"id": "unavailable", "type": "verified-result", "title": "Booking", "eyebrow": "Capability unavailable", "tone": "attention", "frame": _frame(20, 20, 46), "statement": statement, "evidence": [], "timestamp": datetime.now(timezone.utc).isoformat()}
            return ExecutionResult(response=statement, structured_data={"available": False}, ui_composition=_composition(f"reserve-{task.id}", "brain-context", "Booking", statement, [obj]), evidence=[])

        ranked = self.booking_comparator.rank(options, constraints)
        if not ranked:
            raise RuntimeError("No booking option is available to reserve")
        chosen = ranked[0]

        try:
            reserved = await self.booking_reservation.reserve(request, chosen)
        except DuplicateBookingError as error:
            statement = str(error)
            obj = {"id": "duplicate", "type": "verified-result", "title": "Booking", "eyebrow": "Duplicate prevented", "tone": "attention", "frame": _frame(20, 20, 46), "statement": statement, "evidence": [], "timestamp": datetime.now(timezone.utc).isoformat()}
            return ExecutionResult(response=statement, structured_data={"duplicate": True}, ui_composition=_composition(f"reserve-{task.id}", "brain-context", "Booking", statement, [obj]), evidence=[])

        await emit("booking_confirmed", f"Reserved {chosen.name}", {"confirmation_id": reserved.confirmation_id})
        report = self.booking_verifier.verify(reserved, reserved.selected_option())
        tone = "verified" if report.verified else "attention"
        statement = (
            f"{chosen.name} confirmed with ID {reserved.confirmation_id}." if report.verified
            else f"Reservation for {chosen.name} could not be fully verified: {', '.join(report.reasons)}"
        )
        obj = {
            "id": "confirmation", "type": "verified-result", "title": "Booking confirmation", "eyebrow": reserved.status.value,
            "tone": tone, "frame": _frame(16, 18, 48), "statement": statement,
            "evidence": [f"confirmation_id:{reserved.confirmation_id}", f"price:{reserved.final_price}"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        composition = _composition(f"reserve-{task.id}", "brain-context", "Booking confirmed", statement, [obj])
        return ExecutionResult(response=statement, structured_data=reserved.model_dump(mode="json"), ui_composition=composition, evidence=[f"confirmation_id:{reserved.confirmation_id}"])

    # -- Artifacts / delivery --------------------------------------------

    async def _generate_client_report(self, task: Task, emit: EventEmitter) -> ExecutionResult:
        client = extract_client_name(task.user_request) or "Client"
        leads = await self.crm_store.leads()
        client_leads = [lead for lead in leads if client.lower() in lead.company.lower()] or leads[:3]
        counts = await self.crm_store.counts()

        spec = self.report_builder.build(
            title=f"{client} Weekly Report", purpose="Weekly client update", audience=f"{client} stakeholders",
            executive_summary=f"Weekly operating summary for {client}, generated from persistent CRM state.",
            findings=[f"{lead.company}: {lead.state.value} (score {lead.score})" for lead in client_leads] or ["No CRM records matched this client yet."],
            data_notes=f"Pipeline counts: {counts}",
            recommendations=["Continue evidence-based qualification before outreach."],
            risks=["Some sources may be disconnected; see integration health."],
            evidence=[f"crm_lead:{lead.id}" for lead in client_leads] or ["no_matching_crm_records"],
            next_actions=["Review qualified leads for follow-up."],
            data_sources=["Internal CRM"],
            task_id=task.id,
        )

        async def artifact_emit(event_type: str, message: str, payload: dict) -> None:
            await emit(event_type, message, payload)

        record = await self.artifact_engine.create_markdown_report(spec, emit=artifact_emit)
        tone = "verified" if record.verified else "attention"
        obj = {
            "id": "artifact-preview", "type": "artifact-preview", "title": spec.title, "eyebrow": f"{record.status.value} · {record.version}",
            "tone": tone, "frame": _frame(14, 16, 48), "artifactId": record.id, "artifactType": spec.type.value,
            "outputPath": record.output_path, "status": record.status.value, "verified": record.verified,
        }
        statement = f"{spec.title} generated ({record.status.value}). Not sent automatically."
        composition = _composition(f"report-{task.id}", "brain-context", "Client report", statement, [obj])
        return ExecutionResult(response=statement, structured_data=record.model_dump(mode="json"), ui_composition=composition, evidence=[f"artifact_id:{record.id}", f"verified:{record.verified}"])

    async def _generate_presentation(self, task: Task, emit: EventEmitter) -> ExecutionResult:
        topic = extract_research_topic(task.user_request, ("turn the competitor research into a client presentation", "create a presentation about", "build a presentation about")) or "the researched topic"

        async def research_emit(event_type: str, message: str, payload: dict) -> None:
            await emit(event_type, message, payload)

        result = await self.research_task.run(topic, depth=ResearchDepth.STANDARD, emit=research_emit)
        narrative = [("Overview", [claim.statement[:140] for claim in result.claims[:4]] or ["No sufficiently supported findings were available."])]
        if result.contradictions:
            narrative.append(("Open questions", [item.difference[:140] for item in result.contradictions[:4]]))
        narrative.append(("Sources", result.citations[:5] or ["No citable sources were available."]))

        deck = self.presentation_builder.build(title=f"{topic} — Overview", audience="Client leadership", purpose="Decision support", narrative=narrative)
        spec = ArtifactSpec(type=ArtifactType.PRESENTATION, title=f"{topic} — Overview", purpose="Decision support", audience="Client leadership", task_id=task.id)

        async def artifact_emit(event_type: str, message: str, payload: dict) -> None:
            await emit(event_type, message, payload)

        record = await self.artifact_engine.create_presentation(spec, deck, emit=artifact_emit)
        tone = "verified" if record.verified else "attention"
        obj = {
            "id": "presentation-preview", "type": "artifact-preview", "title": spec.title, "eyebrow": f"{record.status.value} · {len(deck.slides)} slide(s)",
            "tone": tone, "frame": _frame(14, 16, 48), "artifactId": record.id, "artifactType": spec.type.value,
            "outputPath": record.output_path, "status": record.status.value, "verified": record.verified,
        }
        statement = f"Presentation '{spec.title}' generated from verified research ({record.status.value})."
        composition = _composition(f"presentation-{task.id}", "brain-context", "Presentation", statement, [obj])
        return ExecutionResult(response=statement, structured_data=record.model_dump(mode="json"), ui_composition=composition, evidence=[f"artifact_id:{record.id}"])

    async def _prepare_client_delivery(self, task: Task, emit: EventEmitter) -> ExecutionResult:
        client = extract_client_name(task.user_request) or "Client"
        artifacts = await self.artifact_engine.store.list(task_id=None)
        eligible = [artifact for artifact in artifacts if artifact.verified][:5]

        package = self.package_builder.build(client=client, project="General", artifacts=eligible)
        report = self.quality_gate.check(
            client=client, project="General", expected_client=client, expected_project="General",
            required_deliverables=[artifact.spec.title for artifact in eligible], artifacts=eligible, manifest=package.manifest,
        )
        await emit("delivery_package_ready", f"Delivery package prepared for {client}", {"passed_quality_gate": report.passed})
        try:
            prepared = await self.delivery_service.prepare(package, quality_report=report)
        except Exception as error:
            statement = f"Delivery preparation blocked: {error}"
            obj = {"id": "blocked", "type": "verified-result", "title": "Delivery", "eyebrow": "Blocked", "tone": "attention", "frame": _frame(20, 20, 46), "statement": statement, "evidence": [], "timestamp": datetime.now(timezone.utc).isoformat()}
            return ExecutionResult(response=statement, structured_data={"blocked": True}, ui_composition=_composition(f"delivery-{task.id}", "brain-context", "Delivery", statement, [obj]), evidence=[])

        await emit("delivery_approval_required", "External send requires explicit approval", {"package_id": prepared.id})
        obj = {
            "id": "manifest", "type": "delivery-manifest", "title": f"Delivery package: {client}", "eyebrow": f"Quality gate: {'passed' if report.passed else 'failed'}",
            "tone": "verified" if report.passed else "attention", "frame": _frame(10, 16, 52),
            "entries": [{"deliverable": entry.deliverable, "file": entry.file, "version": entry.version, "verified": entry.verified} for entry in package.manifest.entries],
            "qualityIssues": report.issues,
        }
        statement = f"Delivery package for {client} prepared ({len(eligible)} deliverable(s)). External send requires approval."
        composition = _composition(f"delivery-{task.id}", "brain-context", "Client delivery", statement, [obj])
        return ExecutionResult(response=statement, structured_data=prepared.model_dump(mode="json"), ui_composition=composition, evidence=[f"package_id:{prepared.id}", f"quality_passed:{report.passed}"])


Phase8Engine = PersonalOSEngine
__all__ = ["PersonalOSEngine", "Phase8Engine"]
