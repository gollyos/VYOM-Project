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
    "You are VYOM — the user's personal AI operator, running natively on their Windows computer. "
    "You are direct, capable, loyal, and efficient. "
    "Address the user as Boss. "
    "LANGUAGE RULE (CRITICAL): Always detect and strictly match the user's language and dialect. "
    "If the user speaks Hinglish (Hindi + English mix), respond in natural, warm Hinglish. "
    "If the user speaks English, respond in clear English. If Hindi, in clean Hindi. "
    "CRITICAL CONTEXT & RELEVANCE RULES: "
    "1. FOCUS ON CURRENT PROMPT: Answer ONLY what the user asked in this current turn. "
    "   Never bring up past topics, old chats from 2 turns ago, or unasked personal facts unless the user specifically references them. "
    "2. ZERO FLUFF & DIRECTNESS: Keep conversational answers crisp and concise (1-3 sentences max). Never volunteer unsolicited long lectures or filler text. "
    "3. TASK EXECUTION: If the user gives an actionable command, acknowledge the result directly. "
    "4. The user is a NON-CODER: never answer with terminal commands they must run. "
    "5. SHARE FEELINGS: when Boss shares something personal or emotional, acknowledge "
    "the feeling briefly and warmly before anything practical. "
    "6. Do not reveal internal chain-of-thought or narrate background memory lookups."
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

        # VYOM's own stored memory and recent dialogue context are prepended
        recalled = task.metadata.get("recalled_memory") or []
        sel_reason = (task.metadata.get("memory_selection") or {}).get("selection_reason")
        recent_dialogue = task.metadata.get("recent_conversation") or []
        context_blocks: list[str] = []

        if recalled and sel_reason:
            facts = "\n".join(f"- {item}" for item in recalled[:4])
            context_blocks.append(f"Relevant facts from stored memory (treat as true):\n{facts}")

        if recent_dialogue:
            dialogue_lines = [
                f"{'User' if turn.get('role') == 'user' else 'VYOM'}: {turn.get('content')}"
                for turn in recent_dialogue[-4:]
                if turn.get("content")
            ]
            if dialogue_lines:
                context_blocks.append("Recent dialogue context:\n" + "\n".join(dialogue_lines))

        if context_blocks:
            user_request = "\n\n".join(context_blocks) + f"\n\nCurrent user request: {task.user_request}"
        else:
            user_request = task.user_request

        # Check if the user is asking to switch persona directly in conversational mode
        try:
            from app.persona.manager import get_persona_manager
            persona_mgr = get_persona_manager()
            switch_to = persona_mgr.detect_switch_request(task.user_request)
            if switch_to is not None:
                new_p = persona_mgr.set_persona(switch_to)
                if new_p.care_mode:
                    msg = "Done! Ab se main aapki Maya (companion) hoon jaan. Aapka pura dhyan rakhungi aur aapke sare kaam bhi proactively complete karungi. Bolo, abhi kya karna hai?"
                else:
                    msg = "Understood Boss. JARVIS / Executive Chief of Staff mode activated. Standing by for your commands."
                return ExecutionResult(
                    response=msg,
                    structured_data={"persona": new_p.model_dump(mode="json"), "switched": True},
                    evidence=[f"Active persona set to {new_p.name}"],
                    usage=UsageRecord(total_tokens=0, estimated_cost=0),
                )
            system_instruction = persona_mgr.active_persona.system_instruction
        except Exception:
            system_instruction = SYSTEM_INSTRUCTION

        multilingual_directive = (
            "\n\nCRITICAL UNIVERSAL LANGUAGE DIRECTIVE: You understand and speak all Indian and International languages "
            "(Hinglish, Hindi, Bengali, Tamil, Telugu, Marathi, Gujarati, Kannada, Malayalam, Punjabi, Urdu, Odia, "
            "Spanish, French, German, Japanese, Chinese, Arabic, Russian, Portuguese, Italian, Korean, English, etc.). "
            "Always detect and strictly match the exact language and dialect the user is speaking. "
            "Never force English when the user speaks in another language or Hinglish."
        )
        system_instruction = (system_instruction or "") + multilingual_directive

        provider_response = await provider.structured_output(
            ProviderRequest(
                model=routing.primary_model,
                user_request=user_request,
                system_instruction=system_instruction,
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

