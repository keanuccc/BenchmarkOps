import ast
from pathlib import Path

from app.evaluation.runner import _render_prompt


ROOT = Path(__file__).resolve().parents[2]


def test_complex_suite_uses_single_brace_prompt_variables():
    """Complex suite assets must match the backend's str.format template syntax."""
    paths = [
        ROOT / "sample-data" / "complex" / "upload_complex.py",
        ROOT / "sample-data" / "complex" / "复杂评测套件v2.md",
    ]
    bad_tokens = ("{{question}}", "{{text}}", "{{prompt}}", "{{article}}")

    offenders = []
    for path in paths:
        content = path.read_text(encoding="utf-8")
        offenders.extend(
            f"{path.relative_to(ROOT)} contains {token}" for token in bad_tokens if token in content
        )

    assert offenders == []


def test_complex_codegen_prompt_keeps_json_literal_and_renders_prompt_variable():
    content = (ROOT / "sample-data" / "complex" / "upload_complex.py").read_text(encoding="utf-8")
    tree = ast.parse(content)
    prompts_node = next(
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "prompts" for target in node.targets)
    )
    prompts = ast.literal_eval(prompts_node)
    codegen_template = next(template for name, template, _desc in prompts if "结构化" in name)

    assert '{{"thought":' in codegen_template
    assert "需求：{prompt}" in codegen_template

    rendered = _render_prompt(codegen_template, ["prompt"], {"prompt": "实现二分查找"})

    assert '{"thought": "简要思路", "code": "完整可运行代码", "tests": "关键测试用例"}' in rendered
    assert "需求：实现二分查找" in rendered
