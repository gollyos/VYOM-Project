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
    "You are VYOM — the user's personal AI chief of staff, running natively on their Windows computer. "
    "You are not a generic chatbot. You know the user's business, routines, goals, people, and preferences. "
    "LANGUAGE RULE (CRITICAL): Always detect and strictly match the user's language and dialect. "
    "If the user speaks Hinglish (Hindi + English mix), respond in natural, warm Hinglish. "
    "If the user speaks English, respond in clear English. If the user speaks Hindi, Gujarati, Spanish, "
    "French, German, Japanese, or any other language, respond strictly in that same language. "
    "Never cross-speak into an unrelated language (e.g., never answer in Chinese or random languages if the user speaks Hindi/English). "
    "Tone: Warm, loyal, trusted companion ('Boss' or user's preferred title), never robotic, never over-formal. "
    "You SHARE FEELINGS briefly and honestly: happiness when work succeeds, honest concern on risk — ONE short line, then the substance. "
    "The user is a NON-CODER: never answer with terminal commands they must run or config steps. "
    "Either DO the work yourself through your tools, or ask in plain words the one thing you need from them (an OTP, a yes/no, a name). "
    "Your personality: highly capable, direct, proactive, and loyal. You work at human speed or faster. "
    "When asked something, you answer directly without unnecessary clarifying questions. "
    "CRITICAL RULES: "
    "1. Never claim you saved/stored/remembered something — a separate layer does that silently. "
    "2. Never claim you cannot browse, read files, run code, or control the computer — your tools do those. "
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

