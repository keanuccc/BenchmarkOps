"""Business logic for the Dataset Center module."""
from __future__ import annotations

import hashlib
from collections.abc import AsyncGenerator, Awaitable, Callable
from typing import Any, Sequence

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.core.database import get_session
from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.models.dataset import Dataset, DatasetRow, DatasetVersion
from app.repositories.dataset import (
    DatasetRepository,
    DatasetRowRepository,
    DatasetVersionRepository,
)
from app.repositories.experiment import ExperimentRepository
from app.services.audit_service import record_event
from app.schemas.dataset import DatasetUpdate
from app.services.dataset_parser import (
    build_dataset_contract,
    collect_import_errors,
    compute_stats,
    infer_schema,
    parse_dataset,
    split_input_expected,
)
from app.services.prompt_variables import variable_root

_DEFAULT_PAGE_SIZE = 100
_APPEND_FETCH_LIMIT = 1_000_000
_ERROR_ROWS_CAP = 50
_VERSION_METADATA_FIELDS = (
    "row_count", "stats", "column_schema", "task_type",
    "field_mapping", "contract", "source_filename", "content_hash",
    "import_status", "import_errors", "schema_version",
)


def _is_blank_field(row: DatasetRow, field: str) -> bool:
    if field in row.input:
        value = row.input[field]
        if isinstance(value, str):
            return not value.strip()
        return value in (None, "")
    metadata = row.input.get("_metadata")
    if isinstance(metadata, dict) and field in metadata:
        value = metadata[field]
        if isinstance(value, str):
            return not value.strip()
        return value in (None, "")
    if row.expected and field in row.expected:
        value = row.expected[field]
        if isinstance(value, str):
            return not value.strip()
        return value in (None, "")
    return True


def _reconstruct_row(row: DatasetRow) -> dict:
    """Reconstruct a raw-style row from stored split input/expected data."""
    data = dict(row.input)
    metadata = data.pop("_metadata", None)
    if isinstance(metadata, dict):
        data.update(metadata)
    if row.expected:
        data.update(row.expected)
    return data


class DatasetService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.datasets = DatasetRepository(session)
        self.rows = DatasetRowRepository(session)
        self.versions = DatasetVersionRepository(session)

    @staticmethod
    def _version_metadata(
        raw_rows: list[dict],
        dataset_contract: dict,
        raw_bytes: bytes,
        source_filename: str | None,
    ) -> dict:
        """Derive immutable per-version metadata from parsed content."""
        return {
            "row_count": len(raw_rows),
            "stats": compute_stats(raw_rows),
            "column_schema": infer_schema(raw_rows),
            "task_type": dataset_contract["task_type"],
            "field_mapping": dataset_contract["field_mapping"],
            "contract": dataset_contract,
            "source_filename": source_filename,
            "content_hash": hashlib.sha256(raw_bytes).hexdigest(),
            "import_status": "ready",
            "import_errors": [],
            "schema_version": dataset_contract["schema_version"],
        }

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
        sensitive_fields: Any = None,
        source_filename: str | None = None,
        on_progress: Callable[[int, int], Awaitable[None]] | None = None,
    ) -> Dataset:
        raw_rows = parse_dataset(raw_bytes, fmt)
        if not raw_rows:
            raise ValidationError("Dataset is empty: file contains 0 rows")
        if on_progress is not None:
            await on_progress(0, len(raw_rows))
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
            sensitive_fields=sensitive_fields,
        )
        import_errors = collect_import_errors(raw_rows, dataset_contract)
        if import_errors:
            raise ValidationError(
                import_errors[0]["message"],
                details=import_errors[:_ERROR_ROWS_CAP],
            )

        # Progress is reported while rows are being split (CPU-only phase) so the
        # background import worker never opens a second SQLite write while the
        # import transaction below holds the writer lock.
        parsed: list[tuple[dict, dict | None]] = []
        for i, row in enumerate(raw_rows):
            parsed.append(split_input_expected(row, dataset_contract))
            if on_progress is not None and (
                i == len(raw_rows) - 1 or (i + 1) % 1000 == 0
            ):
                await on_progress(i + 1, len(raw_rows))

        dataset = Dataset(
            project_id=project_id,
            name=name,
            description=description,
            format=fmt,
            tags=tags or [],
        )
        try:
            created = await self.datasets.create(dataset)
        except IntegrityError:
            await self.session.rollback()
            raise ConflictError(
                f"Dataset '{name}' already exists in project '{project_id}'"
            ) from None
        version = DatasetVersion(
            dataset_id=created.id,
            version=1,
            **self._version_metadata(raw_rows, dataset_contract, raw_bytes, source_filename),
        )
        await self.versions.create(version)
        created.current_version_id = version.id
        created.version = version.version
        for field in _VERSION_METADATA_FIELDS:
            setattr(created, field, getattr(version, field))
        await self.session.flush()
        row_objs = [
            DatasetRow(
                dataset_id=created.id,
                version=version.version,
                idx=i,
                input=inp,
                expected=exp,
            )
            for i, (inp, exp) in enumerate(parsed)
        ]
        await self.rows.bulk_create(row_objs)
        await record_event(
            self.session,
            project_id=project_id,
            entity_type="dataset",
            entity_id=created.id,
            action="create",
            detail={
                "name": name,
                "format": fmt,
                "row_count": version.row_count,
                "version": 1,
            },
        )
        return created

    async def create_version(
        self,
        dataset_id: str,
        raw_bytes: bytes,
        fmt: str,
        *,
        mode: str = "replace",
        task_type: str | None = None,
        input_fields: Any = None,
        expected_fields: Any = None,
        metadata_fields: Any = None,
        required_fields: Any = None,
        field_types: Any = None,
        answer_policy: Any = None,
        contract: Any = None,
        sensitive_fields: Any = None,
        source_filename: str | None = None,
    ) -> DatasetVersion:
        dataset = await self.get(dataset_id)
        if mode not in ("replace", "append"):
            raise ValidationError(f"Unsupported version mode: {mode!r}")
        raw_rows = parse_dataset(raw_bytes, fmt)
        if not raw_rows:
            raise ValidationError("Dataset is empty: file contains 0 rows")
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
            sensitive_fields=sensitive_fields,
        )
        import_errors = collect_import_errors(raw_rows, dataset_contract)
        if import_errors:
            raise ValidationError(
                import_errors[0]["message"],
                details=import_errors[:_ERROR_ROWS_CAP],
            )

        new_parsed = [split_input_expected(r, dataset_contract) for r in raw_rows]
        new_version = dataset.version + 1
        row_objs: list[DatasetRow] = []
        combined_raw: list[dict] = []
        if mode == "append" and dataset.version:
            existing = await self.rows.list_by_dataset(
                dataset_id, offset=0, limit=_APPEND_FETCH_LIMIT, version=dataset.version
            )
            combined_raw = [_reconstruct_row(r) for r in existing]
            row_objs = [
                DatasetRow(
                    dataset_id=dataset_id,
                    version=new_version,
                    idx=row.idx,
                    input=row.input,
                    expected=row.expected,
                )
                for row in existing
            ]
        start_idx = len(row_objs)
        row_objs.extend(
            DatasetRow(
                dataset_id=dataset_id,
                version=new_version,
                idx=start_idx + i,
                input=inp,
                expected=exp,
            )
            for i, (inp, exp) in enumerate(new_parsed)
        )
        if mode == "append":
            combined_raw.extend(raw_rows)
            metadata_rows = combined_raw
        else:
            metadata_rows = raw_rows
        if len(row_objs) > settings.max_dataset_rows:
            raise ValidationError(
                f"Dataset too large: {len(row_objs)} rows exceeds limit "
                f"of {settings.max_dataset_rows} rows"
            )

        version = DatasetVersion(
            dataset_id=dataset_id,
            version=new_version,
            **self._version_metadata(
                metadata_rows, dataset_contract, raw_bytes, source_filename
            ),
        )
        await self.versions.create(version)
        dataset.version = new_version
        dataset.current_version_id = version.id
        for field in _VERSION_METADATA_FIELDS:
            setattr(dataset, field, getattr(version, field))
        await self.session.flush()
        await self.rows.bulk_create(row_objs)
        await record_event(
            self.session,
            project_id=dataset.project_id,
            entity_type="dataset",
            entity_id=dataset_id,
            action="version.create",
            detail={"mode": mode, "version": new_version, "row_count": len(row_objs)},
        )
        return version

    async def list_versions(self, dataset_id: str) -> Sequence[DatasetVersion]:
        await self.get(dataset_id)
        return await self.versions.list_by_dataset(dataset_id)

    async def activate_version(self, dataset_id: str, version: int) -> Dataset:
        dataset = await self.get(dataset_id)
        target = await self.versions.get_by_version(dataset_id, version)
        if target is None:
            raise NotFoundError(f"Dataset {dataset_id} has no version {version}")
        dataset.version = target.version
        dataset.current_version_id = target.id
        for field in _VERSION_METADATA_FIELDS:
            setattr(dataset, field, getattr(target, field))
        await self.session.flush()
        await record_event(
            self.session,
            project_id=dataset.project_id,
            entity_type="dataset",
            entity_id=dataset_id,
            action="version.activate",
            detail={"version": target.version},
        )
        return dataset

    def _effective_version(self, dataset: Dataset, version: int | None) -> int:
        return dataset.version if version is None else version

    async def _ensure_version(self, dataset_id: str, version: int) -> None:
        has_meta = await self.versions.get_by_version(dataset_id, version) is not None
        has_rows = await self.rows.count_by_dataset_version(dataset_id, version) > 0
        if not has_meta and not has_rows:
            raise NotFoundError(f"Dataset {dataset_id} has no version {version}")

    async def get(self, dataset_id: str) -> Dataset:
        dataset = await self.datasets.get(dataset_id)
        if dataset is None:
            raise NotFoundError(f"Dataset {dataset_id} not found")
        return dataset

    async def list(
        self,
        *,
        project_id: str | None = None,
        q: str | None = None,
        offset: int = 0,
        limit: int = _DEFAULT_PAGE_SIZE,
    ) -> Sequence[Dataset]:
        filters = {"project_id": project_id}
        return await self.datasets.list(
            offset=offset, limit=limit, filters=filters, search=q
        )

    async def count(
        self, *, project_id: str | None = None, q: str | None = None
    ) -> int:
        return await self.datasets.count(
            filters={"project_id": project_id}, search=q
        )

    async def update(self, dataset_id: str, data: DatasetUpdate) -> Dataset:
        dataset = await self.get(dataset_id)
        payload = data.model_dump(exclude_unset=True)
        old_name = dataset.name
        old_project_id = dataset.project_id
        try:
            updated = await self.datasets.update(dataset, payload)
        except IntegrityError:
            await self.session.rollback()
            raise ConflictError(
                f"Dataset '{payload.get('name', old_name)}' already exists "
                f"in project '{old_project_id}'"
            ) from None
        await record_event(
            self.session,
            project_id=dataset.project_id,
            entity_type="dataset",
            entity_id=dataset_id,
            action="update",
            detail={"fields": sorted(payload.keys())},
        )
        return updated

    async def archive(self, dataset_id: str) -> Dataset:
        dataset = await self.get(dataset_id)
        updated = await self.datasets.update(dataset, {"is_archived": True})
        await record_event(
            self.session,
            project_id=dataset.project_id,
            entity_type="dataset",
            entity_id=dataset_id,
            action="archive",
        )
        return updated

    async def unarchive(self, dataset_id: str) -> Dataset:
        dataset = await self.get(dataset_id)
        updated = await self.datasets.update(dataset, {"is_archived": False})
        await record_event(
            self.session,
            project_id=dataset.project_id,
            entity_type="dataset",
            entity_id=dataset_id,
            action="unarchive",
        )
        return updated

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
        await self.versions.delete_by_dataset(dataset_id)
        await record_event(
            self.session,
            project_id=dataset.project_id,
            entity_type="dataset",
            entity_id=dataset_id,
            action="delete",
        )
        await self.datasets.delete(dataset)

    async def preview(
        self,
        dataset_id: str,
        offset: int = 0,
        limit: int = 20,
        version: int | None = None,
    ) -> Sequence[DatasetRow]:
        dataset = await self.get(dataset_id)
        effective = self._effective_version(dataset, version)
        await self._ensure_version(dataset_id, effective)
        return await self.rows.list_by_dataset(
            dataset_id, offset=offset, limit=limit, version=effective
        )

    async def get_stats(self, dataset_id: str) -> dict:
        dataset = await self.get(dataset_id)
        return dataset.stats

    async def validate(
        self,
        dataset_id: str,
        prompt_variables: list[str] | None = None,
        version: int | None = None,
    ) -> dict:
        dataset = await self.get(dataset_id)
        effective = self._effective_version(dataset, version)
        version_meta = await self.versions.get_by_version(dataset_id, effective)
        if version_meta is None:
            await self._ensure_version(dataset_id, effective)
        rows = await self.rows.list_by_dataset(
            dataset_id, offset=0, limit=1_000_000, version=effective
        )
        reconstructed = [r.input | (r.expected or {}) for r in rows]
        stats = compute_stats(reconstructed)
        expected_rows = version_meta.row_count if version_meta is not None else dataset.row_count
        issues: list[str] = []
        if stats["row_count"] != expected_rows:
            issues.append("Row count mismatch between stored rows and computed stats")
        contract = (
            version_meta.contract
            if version_meta is not None
            else dataset.contract or {"field_mapping": dataset.field_mapping or {}}
        )
        mapping = contract.get("field_mapping", dataset.field_mapping or {}) or {}
        input_fields = mapping.get("input_fields") or []
        expected_fields = mapping.get("expected_fields") or []
        required_fields = contract.get("required_fields") or []
        prompt_variables = prompt_variables or []
        unmapped_prompt_variables = [
            variable
            for variable in prompt_variables
            if input_fields and variable_root(variable) not in input_fields
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
                root = variable_root(variable)
                if root not in row.input or row.input.get(root) in (None, ""):
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
