"""Tests for VYOM's /learn capability (app/skills/learn.py) - mirrors
Hermes's own agent/learn_prompt.py: point at a real completed task or a
described workflow and derive a reusable skill from it, always
TESTING-status and never auto-activated.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.schemas.results import ExecutionResult
from app.schemas.tasks import PlanStep, Task
from app.skills.learn import LearnService
from app.skills.registry import DuplicateSkillError, SkillRegistry
from app.skills.schemas import SkillStatus


@pytest.fixture
def registry(tmp_path: Path):
    return SkillRegistry(tmp_path / "skills")


@pytest.fixture
def learn_service(registry):
    return LearnService(registry)


def _task_with_plan() -> Task:
    return Task(
        goal="Deploy the app",
        user_request="Build the project, run its tests, then git commit",
        plan=[
            PlanStep(id="s1", title="Run the build", summary="Execute npm run build"),
            PlanStep(id="s2", title="Run pytest", summary="Execute the test suite"),
            PlanStep(id="s3", title="Commit", summary="git commit the result"),
        ],
        result=ExecutionResult(response="Done", evidence=["build exit code 0", "12 tests passed", "commit abc123"]),
    )


def test_from_task_derives_a_skill_with_one_step_per_plan_step(learn_service):
    skill = learn_service.from_task(_task_with_plan())
    assert len(skill.steps) == 3
    assert skill.status == SkillStatus.TESTING  # never auto-activated


def test_from_task_infers_tools_from_step_text(learn_service):
    skill = learn_service.from_task(_task_with_plan())
    tools = [step.tool for step in skill.steps]
    assert tools[0] == "terminal"  # "run the build" -> terminal keyword match
    assert tools[2] == "git"  # "commit" -> git keyword match


def test_from_task_records_real_evidence_in_the_description(learn_service):
    skill = learn_service.from_task(_task_with_plan())
    assert "build exit code 0" in skill.description


def test_from_task_raises_on_a_task_with_no_plan(learn_service):
    empty_task = Task(goal="x", user_request="x", plan=[])
    with pytest.raises(ValueError):
        learn_service.from_task(empty_task)


def test_from_task_registers_the_skill_so_it_is_retrievable(learn_service, registry):
    skill = learn_service.from_task(_task_with_plan())
    fetched = registry.get(skill.id)
    assert fetched is not None
    assert fetched.id == skill.id


def test_from_description_parses_numbered_steps(learn_service):
    description = "1. Open the project file\n2. Run terminal command npm test\n3. git commit the changes"
    skill = learn_service.from_description(description, skill_id="my-workflow", name="My Workflow")
    assert len(skill.steps) == 3
    assert skill.status == SkillStatus.TESTING


def test_from_description_parses_bulleted_steps(learn_service):
    description = "- read the config file\n- run the terminal build command\n- take a screenshot"
    skill = learn_service.from_description(description, skill_id="bulleted-flow", name="Bulleted Flow")
    assert len(skill.steps) == 3
    assert skill.steps[2].tool == "screenshot"


def test_from_description_falls_back_to_plain_lines_when_unstructured(learn_service):
    description = "open the browser\nnavigate to the site\nclick submit"
    skill = learn_service.from_description(description, skill_id="plain-flow", name="Plain Flow")
    assert len(skill.steps) == 3
    assert all(step.tool == "browser" for step in skill.steps)


def test_from_description_raises_on_empty_input(learn_service):
    with pytest.raises(ValueError):
        learn_service.from_description("", skill_id="empty", name="Empty")


def test_learning_the_same_skill_id_twice_raises_duplicate_error(learn_service):
    learn_service.from_description("1. do a thing", skill_id="dupe-test", name="Dupe Test")
    with pytest.raises(DuplicateSkillError):
        learn_service.from_description("1. do another thing", skill_id="dupe-test", name="Dupe Test 2")


def test_default_tool_is_terminal_when_no_keyword_matches(learn_service):
    skill = learn_service.from_description("1. xyzzy plugh frobnicate", skill_id="unknown-verbs", name="Unknown")
    assert skill.steps[0].tool == "terminal"
