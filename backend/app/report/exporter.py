"""Report export helpers: Markdown -> HTML and Markdown -> PDF.

HTML export uses the ``markdown`` package with a clean printable stylesheet.
PDF export uses reportlab (pure Python, works on Windows without GTK), with a
small Markdown subset parser covering the templates produced by this project:
headings, lists, tables, fenced code blocks, and paragraphs.
"""
from __future__ import annotations

import io
import os
import re

import markdown as md
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Paragraph,
    Preformatted,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


def _register_cjk_font() -> str:
    """Register a CJK-capable TTF for Chinese PDF output.

    reportlab's built-in Helvetica cannot render CJK; without a registered
    font every Chinese character becomes a black box. Windows ships SimHei /
    Microsoft YaHei; Linux commonly has Noto Sans CJK.
    """
    candidates = [
        (r"C:\Windows\Fonts\msyh.ttc", "Microsoft YaHei"),
        (r"C:\Windows\Fonts\simhei.ttf", "SimHei"),
        (r"C:\Windows\Fonts\simsun.ttc", "SimSun"),
        ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", "Noto Sans CJK SC"),
        ("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc", "WenQuanYi Zen Hei"),
    ]
    for path, _label in candidates:
        if not os.path.exists(path):
            continue
        try:
            pdfmetrics.registerFont(TTFont("CJK", path, subfontIndex=0))
            return "CJK"
        except Exception:  # noqa: BLE001
            continue
    return "Helvetica"


_CJK_FONT = _register_cjk_font()


def _stylesheet() -> str:
    return """\
<style>
  body { font-family: -apple-system, "Segoe UI", "Microsoft YaHei", sans-serif;
         padding: 2.2em; line-height: 1.65; color: #1a1a1a; max-width: 900px; margin: 0 auto; }
  h1, h2, h3 { color: #111827; margin-top: 1.4em; }
  h1 { font-size: 1.7em; border-bottom: 2px solid #e5e7eb; padding-bottom: .3em; }
  h2 { font-size: 1.3em; }
  table { border-collapse: collapse; width: 100%; margin: 1em 0; font-size: .92em; }
  th, td { border: 1px solid #d1d5db; padding: 7px 10px; text-align: left; }
  th { background: #f3f4f6; }
  pre { background: #f6f8fa; border: 1px solid #e5e7eb; border-radius: 6px;
        padding: 12px; overflow-x: auto; font-size: .88em; }
  code { background: #f6f8fa; padding: 2px 5px; border-radius: 4px;
         font-family: "JetBrains Mono", Consolas, monospace; font-size: .9em; }
  pre code { background: none; padding: 0; }
  blockquote { border-left: 4px solid #d1d5db; margin: 1em 0; padding-left: 1em;
               color: #4b5563; }
</style>
"""


def markdown_to_html(content: str, *, title: str = "BenchmarkOps 评测报告") -> str:
    body = md.markdown(
        content or "",
        extensions=["tables", "fenced_code", "sane_lists", "toc"],
    )
    return f"""\
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>{title}</title>
  {_stylesheet()}
</head>
<body>{body}</body>
</html>
"""


_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_TABLE_ROW_RE = re.compile(r"^\|(.+)\|\s*$")
_BULLET_RE = re.compile(r"^[-*]\s+(.*)$")
_FENCE_RE = re.compile(r"^```(?:\w+)?\s*$")


def _inline(text: str) -> str:
    """Convert the minimal inline Markdown used by report templates."""
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"`([^`]+)`", rf"<font face='{_CJK_FONT}'><i>\1</i></font>", text)
    return text


def markdown_to_pdf(content: str, *, title: str = "BenchmarkOps 评测报告") -> bytes:
    """Render the report's Markdown into PDF bytes via reportlab."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=18 * mm,
        leftMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title=title,
    )
    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("H1", parent=styles["Heading1"], fontName=_CJK_FONT, fontSize=16, spaceAfter=8)
    h2 = ParagraphStyle("H2", parent=styles["Heading2"], fontName=_CJK_FONT, fontSize=13, spaceBefore=10, spaceAfter=5)
    h3 = ParagraphStyle("H3", parent=styles["Heading3"], fontName=_CJK_FONT, fontSize=11.5, spaceBefore=8, spaceAfter=4)
    body = ParagraphStyle("Body", parent=styles["BodyText"], fontName=_CJK_FONT, fontSize=10, leading=15)
    code = ParagraphStyle("Code", parent=styles["Code"], fontName=_CJK_FONT, fontSize=8.5, leading=11)

    story: list = []
    in_code = False
    code_lines: list[str] = []
    table_rows: list[list[str]] = []
    in_table = False

    def _flush_table() -> None:
        nonlocal table_rows, in_table
        if not table_rows:
            return
        data = [[_inline(cell.strip()) for cell in row] for row in table_rows]
        table = Table(data, repeatRows=1, hAlign="LEFT")
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F3F4F6")),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#D1D5DB")),
                    ("FONTNAME", (0, 0), (-1, -1), _CJK_FONT),
                    ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 5),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ]
            )
        )
        story.append(table)
        story.append(Spacer(1, 8))
        table_rows = []
        in_table = False

    def _flush_code() -> None:
        nonlocal code_lines, in_code
        if code_lines:
            story.append(Preformatted("\n".join(code_lines), code))
            story.append(Spacer(1, 8))
        code_lines = []
        in_code = False

    for line in (content or "").splitlines():
        if _FENCE_RE.match(line):
            if in_code:
                _flush_code()
            else:
                in_code = True
            continue
        if in_code:
            code_lines.append(line)
            continue
        if _TABLE_ROW_RE.match(line):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
                continue  # separator row
            if not in_table:
                in_table = True
            table_rows.append(cells)
            continue
        if in_table:
            _flush_table()
        heading = _HEADING_RE.match(line)
        if heading:
            level = len(heading.group(1))
            style = h1 if level == 1 else h2 if level == 2 else h3
            story.append(Paragraph(_inline(heading.group(2)), style))
            continue
        bullet = _BULLET_RE.match(line)
        if bullet:
            story.append(Paragraph(f"• {_inline(bullet.group(1))}", body))
            continue
        if not line.strip():
            story.append(Spacer(1, 4))
            continue
        story.append(Paragraph(_inline(line), body))

    if in_code:
        _flush_code()
    if in_table:
        _flush_table()

    doc.build(story)
    return buffer.getvalue()
