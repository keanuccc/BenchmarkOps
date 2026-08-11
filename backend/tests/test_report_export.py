"""Tests for Markdown -> HTML / PDF report export."""
from __future__ import annotations

from app.report.exporter import markdown_to_html, markdown_to_pdf


def test_markdown_to_html_renders_tables_and_code():
    md_text = """# 标题

## 对比

| 模型 | 准确率 |
|------|--------|
| A    | 100%   |

```python
print("hi")
```
"""
    html = markdown_to_html(md_text, title="报告")
    assert "<html" in html
    assert "<h1" in html
    assert "<table>" in html
    assert "<pre>" in html
    assert "报告" in html


def test_markdown_to_pdf_produces_valid_pdf():
    md_text = """# 评测报告

## 性能分析

- 准确率：100%
- 成本：$0.014

| 模型 | 准确率 |
|------|--------|
| GPT  | 100%   |

```python
def add(a, b):
    return a + b
```
"""
    pdf = markdown_to_pdf(md_text, title="报告")
    assert pdf.startswith(b"%PDF")
    assert len(pdf) > 500
