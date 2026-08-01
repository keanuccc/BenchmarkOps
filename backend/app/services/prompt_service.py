"""Business logic for the Prompt Library module."""
from __future__ import annotations

import re
from collections.abc import AsyncGenerator
from typing import Sequence

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from app.core.database import get_session
from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.models.prompt import Prompt
from app.repositories.experiment import ExperimentRepository
from app.repositories.prompt import PromptRepository
from app.schemas.prompt import PromptUpdate

_VAR_RE = re.compile(r"\{(\w+)\}")


def extract_variables(template: str) -> list[str]:
    seen: list[str] = []
    for match in _VAR_RE.findall(template):
        if match not in seen:
            seen.append(match)
    return seen


class PromptService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.prompts = PromptRepository(session)

    async def create(
        self,
        project_id: str,
        name: str,
        template: str,
        description: str | None,
    ) -> Prompt:
        prompt = Prompt(
            project_id=project_id,
            name=name,
            template=template,
            variables=extract_variables(template),
            description=description,
        )
        try:
            return await self.prompts.create(prompt)
        except IntegrityError:
            await self.session.rollback()
            raise ConflictError(
                f"Prompt '{name}' already exists in project '{project_id}'"
            ) from None

    async def get(self, prompt_id: str) -> Prompt:
        prompt = await self.prompts.get(prompt_id)
        if prompt is None:
            raise NotFoundError(f"Prompt {prompt_id} not found")
        return prompt

    async def list(
        self,
        *,
        project_id: str | None = None,
        q: str | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> Sequence[Prompt]:
        filters = {"project_id": project_id}
        return await self.prompts.list(
            offset=offset, limit=limit, filters=filters, search=q
        )

    async def count(
        self, *, project_id: str | None = None, q: str | None = None
    ) -> int:
        return await self.prompts.count(
            filters={"project_id": project_id}, search=q
        )

    async def update(self, prompt_id: str, data: PromptUpdate) -> Prompt:
        prompt = await self.get(prompt_id)
        payload = data.model_dump(exclude_unset=True)
        if "template" in payload and payload["template"] != prompt.template:
            payload["version"] = prompt.version + 1
            payload["variables"] = extract_variables(payload["template"])
        old_name = prompt.name
        old_project_id = prompt.project_id
        try:
            return await self.prompts.update(prompt, payload)
        except IntegrityError:
            await self.session.rollback()
            raise ConflictError(
                f"Prompt '{payload.get('name', old_name)}' already exists "
                f"in project '{old_project_id}'"
            ) from None

    async def archive(self, prompt_id: str) -> Prompt:
        prompt = await self.get(prompt_id)
        return await self.prompts.update(prompt, {"is_archived": True})

    async def unarchive(self, prompt_id: str) -> Prompt:
        prompt = await self.get(prompt_id)
        return await self.prompts.update(prompt, {"is_archived": False})

    async def delete(self, prompt_id: str) -> None:
        prompt = await self.get(prompt_id)
        references = await ExperimentRepository(self.session).count_by_component(
            prompt_id=prompt_id
        )
        if references:
            raise ConflictError(
                f"Prompt is referenced by {references} experiment(s); "
                "delete those experiments first"
            )
        await self.prompts.delete(prompt)

    async def render(self, prompt_id: str, variables: dict) -> str:
        prompt = await self.get(prompt_id)
        template_vars = set(extract_variables(prompt.template))
        missing = template_vars - set(variables.keys())
        if missing:
            raise ValidationError(f"Missing variables: {sorted(missing)}")
        return prompt.template.format(**variables)


async def get_prompt_service(
    session: AsyncSession = Depends(get_session),
) -> AsyncGenerator[PromptService, None]:
    yield PromptService(session)
