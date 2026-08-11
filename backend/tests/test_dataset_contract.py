"""Dataset contract import and validation behavior."""
from __future__ import annotations

import pytest

from app.core.database import AsyncSessionLocal
from app.core.exceptions import ValidationError
from app.models.dataset import Dataset, DatasetRow
from app.services.dataset_parser import build_dataset_contract, split_input_expected
from app.services.dataset_service import DatasetService


def test_explicit_contract_maps_input_expected_and_metadata() -> None:
    row = {
        "question": "Capital of France?",
        "context": "European capitals",
        "answer": "Paris",
        "domain": "geo",
    }
    contract = build_dataset_contract(
        [row],
        input_fields=["question", "context"],
        expected_fields=["answer"],
        metadata_fields=["domain"],
        required_fields=["question", "answer"],
    )

    input_data, expected = split_input_expected(row, contract)

    assert input_data == {
        "question": "Capital of France?",
        "context": "European capitals",
        "_metadata": {"domain": "geo"},
    }
    assert expected == {"answer": "Paris"}
    assert row["answer"] == "Paris"


def test_contract_rejects_overlapping_field_mapping() -> None:
    rows = [{"question": "2+2?", "answer": "4"}]

    with pytest.raises(ValidationError, match="Field mapped to multiple roles: answer"):
        build_dataset_contract(
            rows,
            input_fields=["question", "answer"],
            expected_fields=["answer"],
        )


def test_contract_rejects_expected_field_missing_from_source() -> None:
    with pytest.raises(ValidationError, match="Expected field 'gold' is not present"):
        build_dataset_contract(
            [{"question": "2+2?", "answer": "4"}],
            input_fields=["question"],
            expected_fields=["gold"],
        )


def test_contract_accepts_legacy_nested_field_mapping() -> None:
    contract = build_dataset_contract(
        [{"question": "2+2?", "answer": "4"}],
        contract={
            "field_mapping": {
                "input_fields": ["question"],
                "expected_fields": ["answer"],
            }
        },
    )

    assert contract["field_mapping"] == {
        "input_fields": ["question"],
        "expected_fields": ["answer"],
        "metadata_fields": [],
    }


def test_contract_rejects_invalid_schema_version() -> None:
    with pytest.raises(ValidationError, match="schema_version"):
        build_dataset_contract(
            [{"question": "2+2?", "answer": "4"}],
            contract={"schema_version": "abc"},
        )


def test_upload_preserves_legacy_answer_inference(client) -> None:
    pid = client.post("/api/v1/projects/", json={"name": "legacy-ds"}).json()["id"]
    jsonl = b'{"question":"2+2?","answer":"4"}\n'

    ds = client.post(
        "/api/v1/datasets/upload",
        data={"project_id": pid, "name": "Legacy", "format": "jsonl"},
        files={"file": ("legacy.jsonl", jsonl, "application/x-ndjson")},
    ).json()

    assert ds["field_mapping"]["input_fields"] == ["question"]
    assert ds["field_mapping"]["expected_fields"] == ["answer"]
    preview = client.get(f"/api/v1/datasets/{ds['id']}/preview").json()
    assert preview[0]["input"] == {"question": "2+2?"}
    assert preview[0]["expected"] == {"answer": "4"}


@pytest.mark.asyncio
async def test_validate_reports_required_expected_and_prompt_variable_issues() -> None:
    async with AsyncSessionLocal() as session:
        contract = {
            "schema_version": 1,
            "task_type": "qa",
            "input_fields": ["question"],
            "expected_fields": ["answer"],
            "metadata_fields": [],
            "required_fields": ["question"],
            "field_mapping": {
                "input_fields": ["question"],
                "expected_fields": ["answer"],
                "metadata_fields": [],
            },
        }
        dataset = Dataset(
            project_id="p1",
            name="bad-contract",
            description=None,
            format="jsonl",
            row_count=1,
            tags=[],
            stats={},
            column_schema=["question", "answer"],
            task_type="qa",
            field_mapping=contract["field_mapping"],
            contract=contract,
        )
        session.add(dataset)
        await session.flush()
        session.add(DatasetRow(dataset_id=dataset.id, idx=0, input={}, expected=None))
        await session.commit()

    async with AsyncSessionLocal() as session:
        service = DatasetService(session)
        result = await service.validate(dataset.id, prompt_variables=["question", "context"])

    assert result["valid"] is False
    assert "Row 0 missing required field: question" in result["issues"]
    assert "Row 0 missing expected field: answer" in result["issues"]
    assert "Prompt variable is not mapped as dataset input: context" in result["issues"]


@pytest.mark.asyncio
async def test_validate_reports_prompt_variable_missing_from_stored_rows() -> None:
    async with AsyncSessionLocal() as session:
        contract = {
            "schema_version": 1,
            "task_type": "qa",
            "input_fields": ["question"],
            "expected_fields": ["answer"],
            "metadata_fields": [],
            "required_fields": [],
            "field_mapping": {
                "input_fields": ["question"],
                "expected_fields": ["answer"],
                "metadata_fields": [],
            },
        }
        dataset = Dataset(
            project_id="p1",
            name="missing-prompt-var",
            description=None,
            format="jsonl",
            row_count=1,
            tags=[],
            stats={},
            column_schema=["question", "answer"],
            task_type="qa",
            field_mapping=contract["field_mapping"],
            contract=contract,
        )
        session.add(dataset)
        await session.flush()
        session.add(
            DatasetRow(
                dataset_id=dataset.id,
                idx=0,
                input={},
                expected={"answer": "4"},
            )
        )
        await session.commit()

    async with AsyncSessionLocal() as session:
        service = DatasetService(session)
        result = await service.validate(dataset.id, prompt_variables=["question"])

    assert result["valid"] is False
    assert "Row 0 missing prompt variable field: question" in result["issues"]


@pytest.mark.asyncio
async def test_upload_rejects_rows_missing_explicit_required_fields() -> None:
    async with AsyncSessionLocal() as session:
        from app.models.project import Project

        project = Project(name="required-fields")
        session.add(project)
        await session.flush()
        service = DatasetService(session)
        with pytest.raises(ValidationError, match="Row 0 missing required field: question"):
            await service.create_from_upload(
                project_id=project.id,
                name="missing-required",
                description=None,
                tags=None,
                fmt="jsonl",
                raw_bytes=b'{"answer":"Paris"}\n',
                input_fields=["question"],
                expected_fields=["answer"],
                required_fields=["question"],
            )
