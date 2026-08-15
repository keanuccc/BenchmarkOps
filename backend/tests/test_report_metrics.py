from app.report.generator import template_report


def test_report_model_id_resolution(monkeypatch) -> None:
    """REPORT_MODEL_ID overrides the built-in default report model."""
    from app.services import report_service as rs

    monkeypatch.setattr(rs.settings, "report_model_id", "deepseek/deepseek-v4-flash")
    assert rs.resolve_report_model_id() == "deepseek/deepseek-v4-flash"

    monkeypatch.setattr(rs.settings, "report_model_id", "")
    monkeypatch.setattr(rs.settings, "default_provider", "deepseek")
    assert rs.resolve_report_model_id() == rs.DEEPSEEK_REPORT_MODEL_ID


def test_report_uses_full_failure_count_not_sample_count() -> None:
    markdown, _ = template_report(
        {
            "experiments": [
                {
                    "name": "Run",
                    "model_name": "Model",
                    "metrics": {
                        "accuracy": 0.5,
                        "rows_failed": 10,
                        "coverage": 0.9,
                        "failure_rate": 0.1,
                    },
                    "total_cost": 0.0,
                    "total_tokens": 0,
                    "sample_failures": [{"row_idx": 1, "score": 0.0, "error": None}],
                }
            ]
        }
    )

    assert "共检查了 **10** 个失败样本" in markdown


def test_report_includes_statistical_significance_verdict() -> None:
    markdown, _ = template_report(
        {
            "experiments": [
                {
                    "name": "Run",
                    "model_name": "Model",
                    "metrics": {"accuracy": 0.5},
                    "total_cost": 0.0,
                    "total_tokens": 0,
                    "sample_failures": [],
                }
            ],
            "statistics": {
                "cmb-medical-qa.jsonl": {
                    "mcnemar_p": 0.0923,
                }
            },
        }
    )
    assert "McNemar p=0.0923" in markdown
    assert "差异未达到统计显著水平" in markdown
