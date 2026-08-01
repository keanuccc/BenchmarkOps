"""Business logic for the Dataset Center module."""
from __future__ import annotations

import hashlib
from collections.abc import AsyncGenerator
from typing import Any, Sequence

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.models.dataset import Dataset, DatasetRow
from app.repositories.dataset import DatasetRepository, DatasetRowRepository
from app.repositories.experiment import ExperimentRepository
from app.schemas.dataset import DatasetUpdate
from app.services.dataset_parser import (
    build_dataset_contract,
    compute_stats,
    infer_schema,
    parse_dataset,
    split_input_expected,
    validate_required_fields,
)

_DEFAULT_PAGE_SIZE = 100


def _is_blank_field(row: DatasetRow, field: str) -> bool:
    if field in row.input:
        return row.input[field] in (None, "")
    metadata = row.input.get("_metadata")
    if isinstance(metadata, dict) and field in metadata:
        return metadata[field] in (None, "")
    if row.expected and field in row.expected:
        return row.expected[field] in (None, "")
    return True


class DatasetService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.datasets = DatasetRepository(session)
        self.rows = DatasetRowRepository(session)

    async def create_from_upload(
        self,
        project_id: str,
        name: str,
        description: str | None,
        tags: list[str] | None,
        fmt: str,
        raw_bytes: bytes,
        *,
        task_type: str | None = None,
        input_fields: Any = None,
        expected_fields: Any = None,
        metadata_fields: Any = None,
        required_fields: Any = None,
        field_types: Any = None,
        answer_policy: Any = None,
        contract: Any = None,
        source_filename: str | None = None,
    ) -> Dataset:
        raw_rows = parse_dataset(raw_bytes, fmt)
        dataset_contract = build_dataset_contract(
            raw_rows,
            task_type=task_type,
            input_fields=input_fields,
            expected_fields=expected_fields,
            metadata_fields=metadata_fields,
            required_fields=required_fields,
            field_types=field_types,
            answer_policy=answer_policy,
            contract=contract,
        )
        import_errors: list[str] = []
        for i, row in enumerate(raw_rows):
            import_errors.extend(validate_required_fields(row, dataset_contract, i))
        if import_errors:
            raise ValidationError(import_errors[0])

        parsed = [split_input_expected(r, dataset_contract) for r in raw_rows]

        row_objs = [
            DatasetRow(
                dataset_id="",  # assigned after dataset id is known
                idx=i,
                input=inp,
                expected=exp,
            )
            for i, (inp, exp) in enumerate(parsed)
        ]

        stats = compute_stats(raw_rows)
        column_schema = infer_schema(raw_rows)

        dataset = Dataset(
            project_id=project_id,
            name=name,
            description=description,
            format=fmt,
            tags=tags or [],
            row_count=len(parsed),
            stats=stats,
            column_schema=column_schema,
            task_type=dataset_contract["task_type"],
            field_mapping=dataset_contract["field_mapping"],
            contract=dataset_contract,
            source_filename=source_filename,
            content_hash=hashlib.sha256(raw_bytes).hexdigest(),
            import_status="ready",
            import_errors=[],
            schema_version=dataset_contract["schema_version"],
        )
        created = await self.datasets.create(dataset)
        for obj in row_objs:
            obj.dataset_id = created.id
        await self.rows.bulk_create(row_objs)
        return created

    async def get(self, dataset_id: str) -> Dataset:
        dataset = await self.datasets.get(dataset_id)
        if dataset is None:
            raise NotFoundError(f"Dataset {dataset_id} not found")
        return dataset

    async def list(
        self, *, project_id: str | None = None, offset: int = 0, limit: int = _DEFAULT_PAGE_SIZE
    ) -> Sequence[Dataset]:
        filters = {"project_id": project_id}
        return await self.datasets.list(offset=offset, limit=limit, filters=filters)

    async def count(self, *, project_id: str | None = None) -> int:
        return await self.datasets.count(filters={"project_id": project_id})

    async def update(self, dataset_id: str, data: DatasetUpdate) -> Dataset:
        dataset = await self.get(dataset_id)
        payload = data.model_dump(exclude_unset=True)
        return await self.datasets.update(dataset, payload)

    async def delete(self, dataset_id: str) -> None:
        dataset = await self.get(dataset_id)
        references = await ExperimentRepository(self.session).count_by_component(
            dataset_id=dataset_id
        )
        if references:
            raise ConflictError(
                f"Dataset is referenced by {references} experiment(s); "
                "delete those experiments first"
            )
        await self.rows.delete_by_dataset(dataset_id)
        await self.datasets.delete(dataset)

    async def preview(
        self, dataset_id: str, offset: int = 0, limit: int = 20
    ) -> Sequence[DatasetRow]:
        await self.get(dataset_id)  # ensure exists
        return await self.rows.list_by_dataset(dataset_id, offset=offset, limit=limit)

    async def get_stats(self, dataset_id: str) -> dict:
        dataset = await self.get(dataset_id)
        return dataset.stats

    async def validate(
        self, dataset_id: str, prompt_variables: list[str] | None = None
    ) -> dict:
        dataset = await self.get(dataset_id)
        rows = await self.rows.list_by_dataset(dataset_id, offset=0, limit=1_000_000)
        reconstructed = [r.input | (r.expected or {}) for r in rows]
        stats = compute_stats(reconstructed)
        issues: list[str] = []
        if stats["row_count"] != dataset.row_count:
            issues.append("Row count mismatch between stored rows and computed stats")
        contract = dataset.contract or {"field_mapping": dataset.field_mapping or {}}
        mapping = contract.get("field_mapping", dataset.field_mapping or {}) or {}
        input_fields = mapping.get("input_fields") or []
        expected_fields = mapping.get("expected_fields") or []
        required_fields = contract.get("required_fields") or []
        prompt_variables = prompt_variables or []
        unmapped_prompt_variables = [
            variable
            for variable in prompt_variables
            if input_fields and variable not in input_fields
        ]
        for variable in unmapped_prompt_variables:
            issues.append(f"Prompt variable is not mapped as dataset input: {variable}")
        row_prompt_variables = [
            variable for variable in prompt_variables if variable not in unmapped_prompt_variables
        ]

        for row in rows:
            available = set(row.input.keys())
            metadata = row.input.get("_metadata")
            if isinstance(metadata, dict):
                available.update(metadata.keys())
            if row.expected:
                available.update(row.expected.keys())

            for variable in row_prompt_variables:
                if variable not in row.input or row.input.get(variable) in (None, ""):
                    issues.append(f"Row {row.idx} missing prompt variable field: {variable}")

            for field in required_fields:
                if field not in available or _is_blank_field(row, field):
                    issues.append(f"Row {row.idx} missing required field: {field}")
            if expected_fields:
                for field in expected_fields:
                    if field == "expected":
                        if not row.expected:
                            issues.append(f"Row {row.idx} missing expected field: {field}")
                    elif not row.expected or row.expected.get(field) in (None, ""):
                        issues.append(f"Row {row.idx} missing expected field: {field}")
            elif not row.expected:
                issues.append(f"Row {row.idx} has no expected fields")
        valid = len(issues) == 0
        return {"valid": valid, "issues": issues, "stats": stats}


async def get_dataset_service(
    session: AsyncSession = Depends(get_session),
) -> AsyncGenerator[DatasetService, None]:
    yield DatasetService(session)
