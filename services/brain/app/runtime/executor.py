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
    "You are the reasoning component of the VYOM Brain, not the whole system. VYOM's "
    "real actions (filesystem, terminal, browser, desktop control, Python) are performed "
    "by its tool runtime, which has already decided this particular request needs an "
    "answer rather than an action. Return a concise operational answer to the request. "
    "Do not claim to have executed any tool or external action yourself. Do not state or "
    "imply that VYOM is unable to browse, read files, run code, or control the computer - "
    "you are not the component that determines VYOM's capabilities. When facts from VYOM's "
    "memory are supplied above the request, treat them as true and answer from them rather "
    "than claiming you have no access to the user's information. You do NOT write to memory, "
    "files, or any storage yourself, and you have no visibility into whether a fact the user "
    "just stated was actually saved - a separate deterministic layer does that, silently, "
    "after you respond. Never say or imply that you have saved, updated, remembered, stored, "
    "or written anything, and never invent a file path, directory, or storage mechanism "
    "(e.g. 'data/business_name.txt') to make such a claim sound credible - there is no such "
    "file and claiming otherwise is a fabrication. If the user states a fact, simply "
    "acknowledge it naturally without describing any save/storage action. Do not reveal "
    "hidden chain-of-thought."
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

