"""Shared response schemas used across modules."""
from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class ListResponse(BaseModel, Generic[T]):
    """Paginated list payload: ``items`` plus the total row count.

    Keeps the previous array behavior under ``items`` while giving clients the
    total so UIs can render page counts / "load more" correctly.
    """

    items: list[T]
    total: int
