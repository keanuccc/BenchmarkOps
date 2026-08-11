"""Report model id must match the gateway actually serving the request."""
from __future__ import annotations

from app.services import report_service


def test_openrouter_default_model(monkeypatch):
    monkeypatch.setattr(report_service.settings, "default_provider", "openrouter")
    monkeypatch.setattr(report_service.settings, "report_provider", "")
    monkeypatch.setattr(report_service.settings, "report_model_id", "")
    assert report_service.resolve_report_model_id() == "openai/gpt-4o-mini"


def test_qiniu_default_model(monkeypatch):
    monkeypatch.setattr(report_service.settings, "default_provider", "qiniu")
    monkeypatch.setattr(report_service.settings, "report_provider", "")
    monkeypatch.setattr(report_service.settings, "report_model_id", "")
    assert report_service.resolve_report_model_id() == "deepseek/deepseek-v4-flash"


def test_explicit_report_model_wins(monkeypatch):
    monkeypatch.setattr(report_service.settings, "report_model_id", "custom/model")
    monkeypatch.setattr(report_service.settings, "default_provider", "qiniu")
    assert report_service.resolve_report_model_id() == "custom/model"
