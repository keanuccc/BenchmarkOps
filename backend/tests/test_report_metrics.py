from app.report.generator import template_report


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
                    "failures": [{"row_idx": 1, "score": 0.0, "error": None}],
                }
            ]
        }
    )

    assert "共检查了 **10** 个失败样本" in markdown
