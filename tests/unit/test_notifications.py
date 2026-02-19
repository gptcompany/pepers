"""Unit tests for services.orchestrator.notifications."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from services.orchestrator.notifications import notify, notify_pipeline_result


# -- notify() --


def test_notify_returns_zero_when_no_urls(monkeypatch):
    monkeypatch.delenv("RP_NOTIFY_URLS", raising=False)
    assert notify("title", "body") == 0


def test_notify_returns_zero_when_urls_empty(monkeypatch):
    monkeypatch.setenv("RP_NOTIFY_URLS", "  ")
    assert notify("title", "body") == 0


@patch("services.orchestrator.notifications.apprise.Apprise")
def test_notify_sends_to_single_target(mock_cls, monkeypatch):
    monkeypatch.setenv("RP_NOTIFY_URLS", "json://localhost/hook")
    instance = MagicMock()
    instance.__len__ = MagicMock(return_value=1)
    mock_cls.return_value = instance

    result = notify("Test Title", "Test Body")

    instance.add.assert_called_once_with("json://localhost/hook")
    instance.notify.assert_called_once_with(title="Test Title", body="Test Body")
    assert result == 1


@patch("services.orchestrator.notifications.apprise.Apprise")
def test_notify_sends_to_multiple_targets(mock_cls, monkeypatch):
    monkeypatch.setenv("RP_NOTIFY_URLS", "json://a, json://b, json://c")
    instance = MagicMock()
    instance.__len__ = MagicMock(return_value=3)
    mock_cls.return_value = instance

    result = notify("T", "B")

    assert instance.add.call_count == 3
    assert result == 3


@patch("services.orchestrator.notifications.apprise.Apprise")
def test_notify_skips_empty_segments(mock_cls, monkeypatch):
    monkeypatch.setenv("RP_NOTIFY_URLS", "json://a,,  ,json://b")
    instance = MagicMock()
    instance.__len__ = MagicMock(return_value=2)
    mock_cls.return_value = instance

    notify("T", "B")

    assert instance.add.call_count == 2
    instance.add.assert_any_call("json://a")
    instance.add.assert_any_call("json://b")


@patch("services.orchestrator.notifications.apprise.Apprise")
def test_notify_returns_zero_on_exception(mock_cls, monkeypatch):
    monkeypatch.setenv("RP_NOTIFY_URLS", "json://a")
    instance = MagicMock()
    instance.__len__ = MagicMock(return_value=1)
    instance.notify.side_effect = Exception("connection refused")
    mock_cls.return_value = instance

    assert notify("T", "B") == 0


# -- notify_pipeline_result() --


@patch("services.orchestrator.notifications.notify")
def test_pipeline_result_completed(mock_notify):
    mock_notify.return_value = 1
    result = {
        "run_id": "run-abc",
        "status": "completed",
        "stages_completed": 5,
        "stages_requested": 5,
        "time_ms": 12345,
        "errors": [],
    }
    notify_pipeline_result(result)

    mock_notify.assert_called_once()
    title, body = mock_notify.call_args[0]
    assert "[OK]" in title
    assert "completed" in title
    assert "run-abc" in body
    assert "5/5" in body
    assert "12.3s" in body


@patch("services.orchestrator.notifications.notify")
def test_pipeline_result_failed_with_errors(mock_notify):
    mock_notify.return_value = 1
    result = {
        "run_id": "run-xyz",
        "status": "failed",
        "stages_completed": 0,
        "stages_requested": 5,
        "time_ms": 500,
        "errors": ["discovery: timeout", "analyzer: 503"],
    }
    notify_pipeline_result(result)

    title, body = mock_notify.call_args[0]
    assert "[FAIL]" in title
    assert "discovery: timeout" in body


@patch("services.orchestrator.notifications.notify")
def test_pipeline_result_partial(mock_notify):
    mock_notify.return_value = 1
    result = {
        "run_id": "run-p",
        "status": "partial",
        "stages_completed": 3,
        "stages_requested": 5,
        "time_ms": 8000,
        "errors": ["validator: CAS down"],
    }
    notify_pipeline_result(result)

    title, body = mock_notify.call_args[0]
    assert "[WARN]" in title
    assert "3/5" in body
