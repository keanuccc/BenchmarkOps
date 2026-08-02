"""Pydantic schemas for the Dataset Center module."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class DatasetContract(BaseModel):
    task_type: str = "qa"
    input_fields: list[str] = Field(default_factory=list)
    expected_fields: list[str] = Field(default_factory=list)
    metadata_fields: list[str] = Field(default_factory=list)
    required_fields: list[str] = Field(default_factory=list)
    field_types: dict = Field(default_factory=dict)
    answer_policy: dict = Field(default_factory=dict)
    sensitive_fields: list[str] = Field(default_factory=list)
    schema_version: int = 1


class DatasetCreate(BaseModel):
    project_id: str
    name: str
    description: str | None = None
    tags: list[str] | None = None


class DatasetUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    tags: list[str] | None = None


class DatasetRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    name: str
    description: str | None
    format: str
    version: int
    row_count: int
    tags: list
    stats: dict
    column_schema: list
    task_type: str = "qa"
    field_mapping: dict = Field(default_factory=dict)
    contract: dict = Field(default_factory=dict)
    source_filename: str | None = None
    content_hash: str | None = None
    current_version_id: str | None = None
    import_status: str = "ready"
    import_errors: list = Field(default_factory=list)
    schema_version: int = 1
    is_archived: bool = False
    created_at: datetime
    updated_at: datetime


class DatasetRowRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    idx: int
    input: dict
    expected: dict | None


class DatasetVersionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    dataset_id: str
    version: int
    row_count: int
    stats: dict
    column_schema: list
    task_type: str = "qa"
    field_mapping: dict = Field(default_factory=dict)
    contract: dict = Field(default_factory=dict)
    source_filename: str | None = None
    content_hash: str | None = None
    import_status: str = "ready"
    import_errors: list = Field(default_factory=list)
    schema_version: int = 1
    created_at: datetime
    updated_at: datetime


class ImportJobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    name: str
    dataset_id: str | None = None
    format: str
    mode: str = "create"
    status: str
    idempotency_key: str | None = None
    content_hash: str | None = None
    source_filename: str | None = None
    total_rows: int = 0
    progress: int = 0
    error: str | None = None
    error_rows: list = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    finished_at: datetime | None = None


class AuditEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str | None = None
    entity_type: str
    entity_id: str
    action: str
    actor: str | None = None
    detail: dict = Field(default_factory=dict)
    created_at: datetime
