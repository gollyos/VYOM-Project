from pathlib import Path
import pytest
from app.runtime.task_classifier import TaskClassifier
from app.schemas.tasks import Task, TaskProfile, TaskDomain
from app.execution.action_engine import ActionEngine
from app.execution.execution_context import ExecutionContextFactory
from app.execution.process_manager import ProcessManager
from app.tools.registry import ToolRegistry


class DummyExecutor:
    async def invoke(self, tool_name: str, payload: dict, context: any):
        class Res:
            success = True
            error = None
            structured_output = {"id": "draft_123", "message_id": "msg_456"}
        return Res()


def create_engine():
    return ActionEngine(
        executor=DummyExecutor(),
        context_factory=ExecutionContextFactory([Path(".")]),
        process_manager=ProcessManager([Path(".")]),
        project_root=Path("."),
    )


@pytest.mark.asyncio
async def test_teach_workflow_classification():
    classifier = TaskClassifier()

    # User teaching in Hindi / Hinglish
    req1 = "अब देखो, मैं तुम्हें सिखा रहा हूं। गाइड बाय गाइड तुम सीखते रहना और जहां पर गलत हो या तो कुछ भी हो तो तुम वो अपने आप ऑप्टिमाइज करना। लाइक अभी देखो, फर्स्ट ऑफ ऑल हमें क्लिक करना है Google Chrome।"
    p1 = classifier.classify(req1)
    assert p1.intent == "teach_workflow"

    req2 = "Vyom, sikho ki kaise Chrome me Gmail open karke mail bhejte hain"
    p2 = classifier.classify(req2)
    assert p2.intent == "teach_workflow"

    req3 = "I am teaching you how to search and deploy code"
    p3 = classifier.classify(req3)
    assert p3.intent == "teach_workflow"


@pytest.mark.asyncio
async def test_send_email_classification_and_execution():
    classifier = TaskClassifier()

    # User asking to send email in Hindi / Hinglish
    req1 = "लिया तो मेरे लिए एक मेल भेज दो gunjan@luxuradesign.space पे।"
    p1 = classifier.classify(req1)
    assert p1.intent == "send_email"

    req2 = "gunjan{at}luxuradesign.space pe ek mail bhej do subject: urgent meeting"
    p2 = classifier.classify(req2)
    assert p2.intent == "send_email"

    # Test ActionEngine execution
    engine = create_engine()
    task = Task(goal=req1, user_request=req1)
    res = await engine._send_email(task, None)
    assert "gunjan@luxuradesign.space" in res.response
    assert "Gmail Compose" in res.response
    assert res.structured_data["to"] == "gunjan@luxuradesign.space"


@pytest.mark.asyncio
async def test_teach_workflow_execution():
    engine = create_engine()
    req = "अब देखो, मैं तुम्हें सिखा रहा हूं। First of all Google Chrome kholna hai, fir Gmail me jaake compose click karna hai aur gunjan@luxuradesign.space ko mail bhejna hai."
    task = Task(goal=req, user_request=req)
    res = await engine._teach_workflow(task, None)

    assert "सिखाया हुआ पूरा वर्कफ़्लो" in res.response or "Learned Workflow" in res.response
    assert "Google Chrome" in res.response
    assert res.structured_data["status"] == "active"
