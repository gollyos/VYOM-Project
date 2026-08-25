from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.automation.events import AutomationEventEngine
from app.automation.scheduler import AutomationScheduler
from app.automation.schemas import Automation, AutomationCreate, AutomationType
from app.automation.store import AutomationStore
from app.devices.authentication import DevicePairingService, PairingError
from app.devices.schemas import DeviceType
from app.persistence.database import Database
from app.core.config import Settings
from app.main import create_app
from app.persistence.task_store import TaskStore
from app.remote.delivery import RemoteDeliveryBridge, RemoteDeliveryStore
from app.runtime.event_bus import EventBus
from app.runtime.task_classifier import TaskClassifier
from app.schemas.approvals import PermissionLevel
from app.schemas.events import BrainEvent, EventType
from app.schemas.results import ExecutionResult
from app.schemas.routing import UsageRecord
from app.schemas.tasks import Task
from app.skills.executor import SkillExecutor
from app.skills.registry import SkillRegistry
from app.skills.schemas import SkillInputSlot, SkillInputType, SkillStep
from app.skills.teachable import TeachableSkillCreate, TeachableSkillService, resolve_templates
from app.tools.result import EvidenceItem, ToolResult


class FakeToolRegistry:
    def get(self, name):
        if name != "fake.write":
            raise KeyError(name)
        return object()


class FakeContextFactory:
    def create(self, task_id, permission, emit):
        return SimpleNamespace(task_id=task_id, permission_level=permission, emit=emit)

    def release(self, task_id):
        return None


class FakeExecutor:
    def __init__(self):
        self.calls = []

    async def invoke(self, name, inputs, context):
        self.calls.append((name, inputs, context.permission_level))
        return ToolResult.completed("verified write", evidence=[EvidenceItem(type="test", summary="write verified")])


async def _emit(*_args):
    return None


async def test_taught_skill_typed_inputs_execute_through_tool_boundary(tmp_path: Path):
    registry = SkillRegistry(tmp_path / "skills")
    service = TeachableSkillService(registry, FakeToolRegistry())
    skill = service.create(TeachableSkillCreate(
        id="save-client-note", name="Save client note", description="Stores a reusable note",
        input_slots=[
            SkillInputSlot(name="client", type=SkillInputType.STRING),
            SkillInputSlot(name="secret", type=SkillInputType.STRING, sensitive=True),
        ],
        steps=[SkillStep(id="write", action="write_note", capability="file.write", tool="fake.write",
                         inputs={"path": "clients/{{client}}.txt", "content": "{{secret}}"})],
    ))
    assert skill.status.value == "testing"
    service.activate(skill.id)
    fake_executor = FakeExecutor()
    action_engine = SimpleNamespace(executor=fake_executor, context_factory=FakeContextFactory())
    result = await SkillExecutor(registry, action_engine).execute(
        skill.id, Task(goal="run", user_request="run", permission_level=PermissionLevel.L1,
                       metadata={"provenance": "USER_COMMAND"}),
        _emit, {"client": "acme", "secret": "private"},
    )
    assert result.response.startswith("Taught skill")
    assert fake_executor.calls[0][1] == {"path": "clients/acme.txt", "content": "private"}
    assert "private" not in result.model_dump_json()


def test_taught_skill_rejects_unknown_placeholders_and_preserves_typed_exact_values():
    assert resolve_templates({"count": "{{count}}"}, {"count": 3}) == {"count": 3}
    with pytest.raises(ValueError, match="Unknown input placeholders"):
        TeachableSkillCreate(
            id="bad-skill", name="Bad", description="Bad",
            steps=[SkillStep(id="one", action="one", capability="x", tool="fake.write",
                             inputs={"value": "{{missing}}"})],
        )


async def test_conditional_automation_fires_once_per_event_and_debounces(tmp_path: Path):
    database = Database(tmp_path / "events.db")
    await database.connect()
    store = AutomationStore(database)
    calls = []

    async def action(automation):
        calls.append(automation.id)
        return {"task_id": "task_spawned", "summary": "started"}

    scheduler = AutomationScheduler(store, action)
    engine = AutomationEventEngine(store, scheduler, EventBus())
    automation = Automation.from_create(AutomationCreate(
        name="React to verified file", type=AutomationType.CONDITIONAL,
        action="run_vyom_command", condition={
            "event_type": "file_changed", "filters": {"path": "report.md"},
            "debounce_seconds": 60, "command": "review report.md",
        },
    ))
    await store.save(automation)
    event = BrainEvent(task_id="source", type=EventType.FILE_CHANGED,
                       human_readable_message="changed", structured_payload={"path": "report.md"})
    first = await engine.handle(event)
    duplicate = await engine.handle(event)
    assert len(first) == 1 and duplicate == [] and calls == [automation.id]
    assert (await store.get(automation.id)).run_count == 1
    await database.close()


def test_pairing_claim_is_one_time_and_requires_original_code():
    pairing = DevicePairingService()
    request = pairing.start_pairing("Phone", DeviceType.MOBILE, "android", [])
    node, token = pairing.approve(request.request_id, allowed_capabilities=[])
    with pytest.raises(PairingError, match="does not match"):
        pairing.claim(request.request_id, "wrong")
    claimed_node, claimed_token = pairing.claim(request.request_id, request.code)
    assert claimed_node.node_id == node.node_id and claimed_token == token
    with pytest.raises(PairingError, match="Unknown"):
        pairing.claim(request.request_id, request.code)


async def test_remote_result_delivery_is_durable_and_acknowledged(tmp_path: Path):
    database = Database(tmp_path / "delivery.db")
    await database.connect()
    tasks = TaskStore(database)
    deliveries = RemoteDeliveryStore(database)
    bridge = RemoteDeliveryBridge(EventBus(), tasks, deliveries)
    task = Task(
        goal="remote", user_request="status", source="remote:phone-1", status="completed",
        result=ExecutionResult(response="All clear", evidence=["verified"], usage=UsageRecord(total_tokens=0, estimated_cost=0)),
    )
    await tasks.save(task)
    delivery = await bridge.handle(BrainEvent(
        task_id=task.id, type=EventType.TASK_COMPLETED, human_readable_message="done",
    ))
    assert delivery is not None and delivery.payload["summary"] == "All clear"
    assert len(await deliveries.pending("phone-1")) == 1
    await deliveries.acknowledge("phone-1", delivery.delivery_id)
    assert await deliveries.pending("phone-1") == []
    await database.close()


def test_brain_graph_and_taught_skill_commands_route_deterministically():
    classifier = TaskClassifier()
    assert classifier.classify("show my brain connections").intent == "show_brain_graph"
    profile = classifier.classify('run skill save-client-note with {"client":"acme","secret":"x"}')
    assert profile.intent == "run_taught_skill" and profile.deterministic


def test_live_app_brain_composition_and_authenticated_phone_pairing(tmp_path: Path):
    settings = Settings(
        database_path=tmp_path / "app.db", skills_root=tmp_path / "skills", agents_root=tmp_path / "agents",
        audit_log_path=tmp_path / "audit.jsonl", secret_store_path=tmp_path / "secrets",
        artifacts_root=tmp_path / "artifacts", backup_root=tmp_path / "backups",
        tool_registry_path=Path(__file__).parent / "fixtures" / "tools_no_mcp.yaml",
    )
    with TestClient(create_app(settings)) as client:
        composition = client.get("/api/brain-graph/composition")
        assert composition.status_code == 200
        graph = composition.json()["objects"][0]
        assert graph["type"] == "brain-graph" and graph["nodes"][0]["id"] == "core:vyom"

        pairing = client.post("/api/devices/pair", json={
            "name": "Test phone", "device_type": "mobile", "platform": "android",
            "requested_capabilities": ["notifications.send"],
        }).json()
        pending = client.get("/api/devices/pair/pending").json()
        assert pending[0]["request_id"] == pairing["request_id"] and "code" not in pending[0]
        approved = client.post(
            f"/api/devices/pair/{pairing['request_id']}/approve",
            json={"allowed_capabilities": ["notifications.send"]},
        )
        assert approved.status_code == 200
        claim = client.post(
            f"/api/devices/pair/{pairing['request_id']}/claim", json={"code": pairing["code"]},
        )
        assert claim.status_code == 200
        credential = claim.json()
        session = client.post("/api/remote/session", json={
            "node_id": credential["node"]["node_id"], "token": credential["token"],
        })
        assert session.status_code == 200
        auth_headers = {
            "X-VYOM-Node-ID": credential["node"]["node_id"],
            "X-VYOM-Session": session.json()["session_id"],
        }
        assert client.get("/api/remote/approvals", headers=auth_headers).status_code == 200
        assert client.get("/api/remote/approvals").status_code == 422
        deliveries = client.get("/api/remote/deliveries", headers={
            **auth_headers,
        })
        assert deliveries.status_code == 200 and deliveries.json() == []
