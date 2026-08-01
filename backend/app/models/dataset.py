"""ORM models for the Dataset Center module (datasets + their rows)."""
from __future__ import annotations

from sqlalchemy import Boolean, CheckConstraint, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, JSONType, TimestampMixin, UUIDMixin


class Dataset(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "datasets"
    __table_args__ = (
        CheckConstraint(
            "format IN ('csv', 'json', 'jsonl')", name="ck_datasets_format"
        ),
        UniqueConstraint("project_id", "name", name="uq_datasets_project_name"),
    )

    project_id: Mapped[str] = mapped_column(String(36), index=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    format: Mapped[str] = mapped_column(String(10))  # csv | json | jsonl
    version: Mapped[int] = mapped_column(Integer, default=1)
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    tags: Mapped[list] = mapped_column(JSONType, default=list)
    stats: Mapped[dict] = mapped_column(JSONType, default=dict)
    column_schema: Mapped[list] = mapped_column(JSONType, default=list)
    task_type: Mapped[str] = mapped_column(String(50), default="qa")
    field_mapping: Mapped[dict] = mapped_column(JSONType, default=dict)
    contract: Mapped[dict] = mapped_column(JSONType, default=dict)
    source_filename: Mapped[str | None] = mapped_column(Text)
    content_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    import_status: Mapped[str] = mapped_column(String(20), default="ready")
    import_errors: Mapped[list] = mapped_column(JSONType, default=list)
    schema_version: Mapped[int] = mapped_column(Integer, default=1)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False)


class DatasetRow(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "dataset_rows"
    __table_args__ = (
        UniqueConstraint("dataset_id", "idx", name="uq_dataset_rows_dataset_idx"),
    )

    dataset_id: Mapped[str] = mapped_column(String(36), index=True)
    idx: Mapped[int] = mapped_column(Integer)
    input: Mapped[dict] = mapped_column(JSONType, default=dict)
    expected: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
