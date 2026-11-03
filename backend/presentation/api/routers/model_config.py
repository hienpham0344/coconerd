from dataclasses import asdict

from fastapi import APIRouter, Depends, Query

from backend.application.ports.persistence import UnitOfWork
from backend.application.read_models import ModelConfiguration
from backend.application.services import model_config
from backend.presentation.api.dependencies import ApiDependencies
from backend.presentation.api.schemas import (
    ModelConfigRequest,
    ModelConfigResponse,
)


def create_router(dependencies: ApiDependencies) -> APIRouter:
    router = APIRouter()

    @router.put(
        "/api/v1/admin/model-config",
        response_model=ModelConfigResponse,
        tags=["admin"],
        dependencies=dependencies.admin,
    )
    async def set_model_config(
        body: ModelConfigRequest,
        guild_id: str | None = Query(default=None, max_length=100),
        uow: UnitOfWork = Depends(dependencies.get_uow),
    ) -> ModelConfigResponse:
        result = await model_config.set_model_config(
            uow,
            guild_id,
            body.provider,
            body.model_id,
            body.temperature,
            body.max_tokens,
        )
        return ModelConfigResponse(**asdict(result))

    @router.get(
        "/api/v1/admin/model-config",
        response_model=ModelConfigResponse,
        tags=["admin"],
        dependencies=dependencies.admin,
    )
    async def get_model_config(
        guild_id: str | None = Query(default=None, max_length=100),
        uow: UnitOfWork = Depends(dependencies.get_uow),
    ) -> ModelConfigResponse:
        default = ModelConfiguration(
            "global",
            None,
            "meta",
            dependencies.settings.meta_model_name,
            dependencies.settings.llm_temperature,
            dependencies.settings.llm_max_tokens,
        )
        result = await model_config.get_model_config(uow, guild_id, default)
        return ModelConfigResponse(**asdict(result))

    return router
