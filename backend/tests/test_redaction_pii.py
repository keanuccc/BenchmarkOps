"""Tests for field-level and text-level PII redaction."""
from __future__ import annotations

from app.services.redaction import redact_values


def test_field_level_redaction():
    out = redact_values(
        {"phone": "13800138000", "name": "张三", "_metadata": {"phone": "13900139000"}},
        {"phone"},
    )
    assert out["phone"] == "[REDACTED]"
    assert out["name"] == "张三"
    assert out["_metadata"]["phone"] == "[REDACTED]"


def test_text_level_redaction_masks_phone_and_email():
    out = redact_values(
        {"question": "我的手机号 13800138000，邮箱 a@b.com 能改吗"},
        {"phone"},
    )
    assert "13800138000" not in out["question"]
    assert "a@b.com" not in out["question"]
    assert "[REDACTED]" in out["question"]


def test_nested_list_redaction():
    out = redact_values(
        {"history": [{"text": "电话 13800138000"}, "13800138000 请回电"]},
        {"phone"},
    )
    assert "13800138000" not in str(out)


def test_plain_values_untouched():
    out = redact_values(
        {"answer": "退款需要1-3个工作日", "score": 1.0, "ok": True},
        {"score"},
    )
    assert out["answer"] == "退款需要1-3个工作日"
    assert out["score"] == "[REDACTED]"
    assert out["ok"] is True


def test_undeclared_dataset_passes_through():
    out = redact_values(
        {"question": "电话 13800138000", "answer": "ok"},
        set(),
    )
    assert out["question"] == "电话 13800138000"


def test_redact_text_standalone():
    from app.services.redaction import redact_text

    assert "13800138000" not in redact_text("手机 13800138000 联系")
    assert redact_text("普通文本") == "普通文本"
