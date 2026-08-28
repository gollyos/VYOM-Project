import pytest
from app.automation.workflow_engine import WorkflowEngine, WorkflowStep, StepType, StepStatus
from app.automation.natural_builder import NaturalAutomationBuilder


@pytest.mark.asyncio
async def test_workflow_engine_execution_flow():
    engine = WorkflowEngine()

    steps = [
        WorkflowStep(
            name="Fetch Context",
            type=StepType.TOOL_CALL,
            tool="mock.fetch_data",
            input_template={"query": "active_users"},
        ),
        WorkflowStep(
            name="Analyze Context",
            type=StepType.AI_STEP,
            prompt="Analyze the user count",
            input_template={"data": "{{steps.step_1.output}}"},
        ),
        WorkflowStep(
            name="Trigger Action",
            type=StepType.ACTION,
            input_template={"status": "completed", "result": "{{steps.step_2.output.summary}}"},
        ),
    ]

    run = await engine.execute_workflow(
        workflow_id="wf_test_101",
        workflow_name="User Analytics Pipeline",
        steps=steps,
        trigger_data={"env": "production"},
    )

    assert run.status == "completed"
    assert len(run.step_runs) == 3
    assert run.step_runs[0].status == StepStatus.COMPLETED
    assert run.step_runs[1].status == StepStatus.COMPLETED
    assert run.step_runs[2].status == StepStatus.COMPLETED
    assert run.step_runs[0].duration_ms >= 0


@pytest.mark.asyncio
async def test_workflow_engine_approval_gate():
    engine = WorkflowEngine()

    steps = [
        WorkflowStep(
            name="Safe Read",
            type=StepType.TOOL_CALL,
            tool="mock.read",
            input_template={"path": "/logs"},
        ),
        WorkflowStep(
            name="Dangerous Deploy",
            type=StepType.TOOL_CALL,
            tool="mock.deploy",
            input_template={"version": "2.0"},
            requires_approval=True,
            approval_reason="External production deployment requires human approval",
        ),
    ]

    run = await engine.execute_workflow(
        workflow_id="wf_deploy_202",
        workflow_name="Production Deploy Pipeline",
        steps=steps,
    )

    # Workflow must pause at approval gate
    assert run.status == "waiting_approval"
    assert run.step_runs[1].status == StepStatus.WAITING_APPROVAL


def test_natural_automation_builder():
    prompt = "Every weekday at 9 AM check my GitHub issues, summarize high priority ones and prepare an email digest"
    parsed = NaturalAutomationBuilder.parse_instruction(prompt)

    assert parsed["trigger_type"] == "recurring"
    assert parsed["cron_expression"] == "0 9 * * 1-5"
    assert len(parsed["steps"]) >= 2
    assert any(s["tool"] == "github.search_issues" for s in parsed["steps"])
    assert any(s["type"] == "ai_step" for s in parsed["steps"])
