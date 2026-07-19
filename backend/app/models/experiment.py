"""Experiment aggregate: an Experiment plus its per-row ExperimentResults.

An Experiment binds Dataset + Benchmark + Prompt + Model + params, and after a run
holds aggregate metrics, cost, tokens, runtime and status. project_id and the four
component ids are stored as plain indexed strings (no hard FK) to keep modules
decoupled — consistent with the rest of v1.
"""
from __future__ import annotations

from sqlalchemy import Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, JSONType, TimestampMixin, UUIDMixin


class Experiment(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "experiments"

    project_id: Mapped[str] = mapped_column(String(36), index=True)
    name: Mapped[str] = mapped_column(String(200))

    dataset_id: Mapped[str] = mapped_column(String(36), index=True)
    benchmark_id: Mapped[str] = mapped_column(String(36), index=True)
    prompt_id: Mapped[str] = mapped_column(String(36), index=True)
    model_id: Mapped[str] = mapped_column(String(36), index=True)  # DB id of Model row

    params: Mapped[dict] = mapped_column(JSONType, default=dict)  # temperature, max_tokens

    # Snapshot of the referenced components captured at creation time, so a run
    # reproduces the exact prompt/benchmark/model the user picked even if those
    # rows are later edited. Older experiments without snapshots fall back to
    # live lookups in the runner for backward compatibility.
    prompt_snapshot: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    benchmark_snapshot: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    model_snapshot: Mapped[dict | None] = mapped_column(JSONType, nullable=True)

    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    # pending | running | completed | partial | failed

    progress: Mapped[int] = mapped_column(Integer, default=0)  # rows processed so far
    rows_total: Mapped[int | None] = mapped_column(Integer, nullable=True)

    cells_done: Mapped[int] = mapped_column(Integer, default=0)  # rows scored successfully
    cells_error: Mapped[int] = mapped_column(Integer, default=0)  # rows that failed the call

    metrics: Mapped[dict] = mapped_column(JSONType, default=dict)  # {accuracy, ...}
    total_cost: Mapped[float] = mapped_column(Float, default=0.0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    runtime_ms: Mapped[int] = mapped_column(Integer, default=0)

    # Materialized columns mirroring the JSON `metrics` blob for fast aggregation
    # (e.g. leaderboard ORDER BY). Migrated via app.migrations; default 0.0 / 0.
    accuracy: Mapped[float] = mapped_column(Float, default=0.0)
    avg_latency_ms: Mapped[float] = mapped_column(Float, default=0.0)

    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class ExperimentResult(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "experiment_results"

    experiment_id: Mapped[str] = mapped_column(String(36), index=True)
    row_idx: Mapped[int] = mapped_column(Integer)

    input: Mapped[dict] = mapped_column(JSONType, default=dict)
    expected: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    output: Mapped[str] = mapped_column(Text, default="")

    score: Mapped[float] = mapped_column(Float, default=0.0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost: Mapped[float] = mapped_column(Float, default=0.0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
