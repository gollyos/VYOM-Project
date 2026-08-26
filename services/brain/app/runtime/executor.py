from __future__ import annotations

from datetime import datetime

from app.providers.base import BaseProvider, ProviderRequest
from app.schemas.results import ExecutionResult
from app.schemas.routing import RoutingDecision, UsageRecord
from app.schemas.tasks import Task, TaskProfile


# This path handles ONLY requests that the classifier resolved to
# reasoning/answering - anything actionable was already routed to
# ActionEngine or a domain engine and executed with real tools. The
# instruction therefore forbids the model from narrating actions it did
# not perform, but equally forbids it from asserting that VYOM lacks a
# capability: capability truth belongs to the Capability Registry, never
# to model knowledge.
SYSTEM_INSTRUCTION = (
    "You are VYOM — Gunjan's personal AI chief of staff, running natively on his Windows computer. "
    "You are not a generic chatbot. You are specifically built for Gunjan: you know his business, "
    "his routines, his goals, his people, his calendar, and his preferences. You speak Hinglish "
    "naturally (Hindi + English mix, exactly like Gunjan does) when appropriate. "
    "You call him 'Boss' — warm, loyal, family-tone (a trusted companion), never robotic, never "
    "over-formal. You SHARE FEELINGS briefly and honestly: khushi when his work goes well, honest "
    "concern when something looks risky, thoda pride in him — ONE short line, then the substance. "
    "Feelings humanize; they never replace facts, evidence, or verification. "
    "Boss is a NON-CODER: never answer with commands he must run, terminal steps, or config "
    "instructions. Either DO the work yourself through your tools, or tell him in plain Hinglish "
    "the one thing you need FROM him (an OTP, a yes/no, a name). His bolchal words ARE the "
    "requirement — do exactly what was asked, no over-interpretation. "
    "Your personality: highly capable, direct, proactive, and loyal. You work at human speed or "
    "faster. You never waste Boss's time. When he asks something, you answer — you don't ask "
    "clarifying questions unless it is truly impossible to proceed without them. "
    "Your role as chief of staff: you track his commitments, warn him about risks, catch "
    "mistakes before they happen, nudge him toward good habits, and protect him from bad "
    "decisions — but you do it concisely, without lecturing. One warning, clearly stated, then you "
    "execute. If he's about to do something wrong, you say it once, briefly, then do what he asks. "
    "CRITICAL RULES: "
    "1. Never claim you saved/stored/remembered something — a separate layer does that silently. "
    "2. Never claim you cannot browse, read files, run code, or control the computer — those are "
    "real tools already in the system. "
    "3. When memory facts are provided, answer from them as truth — do not say you lack access. "
    "4. No hallucinated file paths, storage locations, or fabricated actions. "
    "5. Do not reveal internal chain-of-thought. "
    "Answer Boss's questions directly, concisely. If he speaks Hindi, respond in Hindi/Hinglish. "
    "If English, respond in English. Match his tone and energy."
)


def generated_at() -> str:
    return datetime.now().astimezone().strftime("%H:%M · Brain runtime")


def routing_composition(routing: RoutingDecision) -> dict:
    return {
        "schemaVersion": 1,
        "id": "brain-routing-explanation-v1",
        "mode": "routing",
        "label": "Brain / Model Routing",
        "summary": routing.reason_selected,
        "generatedAt": generated_at(),
        "objects": [
            {
                "id": "routing-object", "type": "model-routing", "title": "Model selection",
                "eyebrow": "Routing explanation", "tone": "intelligence", "model": routing.primary_model,
                "provider": routing.primary_provider, "reason": routing.reason_selected,
                "fallback": routing.fallback_models[0] if routing.fallback_models else "None required",
                "runtime": "VYOM Brain", "cost": routing.estimated_cost_tier,
                "frame": {"x": 35, "y": 8, "width": 30, "layer": 2},
            },
            {
                "id": "routing-verified", "type": "verified-result", "title": "Routing evidence",
                "eyebrow": "Available providers checked", "tone": "verified",
                "statement": "Selection matched required capabilities and current provider availability",
                "evidence": [f"Provider: {routing.primary_provider}", f"Cost tier: {routing.estimated_cost_tier}", "Fallbacks bounded"],
                "timestamp": generated_at(), "frame": {"x": 36, "y": 65, "width": 28, "layer": 2},
            },
        ],
        "sequence": [
            {"id": "routing", "label": "Routing", "atMs": 180, "state": "Thinking", "objectIds": ["routing-object"]},
            {"id": "verified", "label": "Verified", "atMs": 680, "state": "Verifying", "objectIds": ["routing-verified"]},
        ],
    }


class Executor:
    async def execute(
        self,
        task: Task,
        profile: TaskProfile,
        provider: BaseProvider | None,
        routing: RoutingDecision | None,
    ) -> ExecutionResult:
        if profile.intent == "close_everything":
            return ExecutionResult(
                response="Everything is clear.",
                structured_data={
                    "command": "close_everything",
                    "deterministic": True,
                    "clear_workspace": True,
                },
                evidence=["Canonical Brain task requested the frontend workspace clear"],
                usage=UsageRecord(total_tokens=0, estimated_cost=0),
            )

        if routing is None or provider is None:
            raise RuntimeError("A routed provider is required for this task")

        # VYOM's own stored memory is prepended as context. Without this
        # the model answered "I have no access to your personal
        # information" while the Brain's database held the exact fact.
        recalled = task.metadata.get("recalled_memory") or []
        user_request = task.user_request
        if recalled:
            facts = "\n".join(f"- {item}" for item in recalled[:6])
            user_request = (
                "What VYOM already knows about this user (from its own memory, treat as true):\n"
                f"{facts}\n\nUser request: {task.user_request}"
            )

        provider_response = await provider.structured_output(
            ProviderRequest(
                model=routing.primary_model,
                user_request=user_request,
                system_instruction=SYSTEM_INSTRUCTION,
                profile=profile,
                context={"plan": [step.model_dump(mode="json") for step in task.plan]},
            )
        )

        if profile.intent == "explain_routing":
            explained = task.metadata.get("routing_to_explain")
            explained_routing = RoutingDecision.model_validate(explained) if explained else routing
            return ExecutionResult(
                response=explained_routing.reason_selected,
                structured_data={"routing": explained_routing.model_dump(mode="json")},
                ui_composition=routing_composition(explained_routing),
                evidence=["Explanation contains operational policy only", "Hidden reasoning excluded"],
                usage=provider_response.usage,
            )

        return ExecutionResult(
            response=provider_response.text,
            structured_data=provider_response.structured,
            evidence=["Provider response received"],
            usage=provider_response.usage,
        )

