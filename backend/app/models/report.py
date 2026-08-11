"""AI Report ORM model — a generated Markdown report about one or more experiments.

project_id and experiment_ids are plain strings/JSON (no hard FK) so the report
module stays decoupled from the experiment module, consistent with v1 conventions.
"""
from __future__ import annotations

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, JSONType, TimestampMixin, UUIDMixin


class Report(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "reports"

    project_id: Mapped[str] = mapped_column(String(36), index=True)
    organization_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True, index=True
    )
    title: Mapped[str] = mapped_column(String(300))

    experiment_ids: Mapped[list] = mapped_column(JSONType, default=list)

    content_markdown: Mapped[str] = mapped_column(Text, default="")
    # {executive_summary, performance_analysis, cost_analysis,
    #  failure_analysis, recommendations, next_actions}
    sections: Mapped[dict] = mapped_column(JSONType, default=dict)

    # "openrouter" | "mock" | "template"
    generated_by: Mapped[str] = mapped_column(String(30), default="template")
