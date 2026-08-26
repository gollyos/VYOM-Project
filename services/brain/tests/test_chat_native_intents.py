"""Tests for the chat-native MCP-connect and learn-skill classifier
intents, and the FailureAnalyzer retriable classification that backs
the self-healing retry loop.
"""
from __future__ import annotations

from app.learning.failure_analyzer import FailureAnalyzer
from app.runtime.task_classifier import TaskClassifier


def test_connect_to_x_mcp_classifies_as_mcp_connect():
    classifier = TaskClassifier()
    profile = classifier.classify("connect to notion mcp")
    assert profile.intent == "mcp_connect"
    assert profile.deterministic is True


def test_add_the_x_mcp_server_classifies_as_mcp_connect():
    classifier = TaskClassifier()
    profile = classifier.classify("add the slack mcp server")
    assert profile.intent == "mcp_connect"


def test_connect_without_mcp_word_does_not_misfire():
    """'connect' alone is too common a verb - only requests that
    explicitly say 'mcp' should route to mcp_connect."""
    classifier = TaskClassifier()
    profile = classifier.classify("connect my phone to this laptop")
    assert profile.intent != "mcp_connect"


def test_learn_how_to_classifies_as_learn_skill():
    classifier = TaskClassifier()
    profile = classifier.classify("learn how to deploy: 1. build 2. test 3. commit")
    assert profile.intent == "learn_skill"
    assert profile.deterministic is True


def test_learn_this_workflow_classifies_as_learn_skill():
    classifier = TaskClassifier()
    profile = classifier.classify("learn this workflow: open file, run tests, commit")
    assert profile.intent == "learn_skill"


def test_unrelated_learn_sentence_does_not_misfire():
    classifier = TaskClassifier()
    profile = classifier.classify("what did I learn yesterday?")
    assert profile.intent != "learn_skill"


def test_failure_analyzer_marks_minimized_window_error_as_retriable():
    analyzer = FailureAnalyzer()
    analysis = analyzer.analyze("No visible window matching 'Calculator'")
    assert analysis is not None
    assert analysis["retriable"] is True


def test_failure_analyzer_marks_timeout_as_retriable():
    analyzer = FailureAnalyzer()
    analysis = analyzer.analyze("Operation timed out after 30s")
    assert analysis["retriable"] is True


def test_failure_analyzer_marks_missing_dependency_as_not_retriable():
    """A structural failure (a missing module) will fail identically on
    a bare retry - it needs a different plan, not another attempt."""
    analyzer = FailureAnalyzer()
    analysis = analyzer.analyze("Cannot find module react")
    assert analysis["retriable"] is False


def test_failure_analyzer_marks_permission_denied_as_not_retriable():
    analyzer = FailureAnalyzer()
    analysis = analyzer.analyze("Permission denied: access denied to path")
    assert analysis["retriable"] is False
