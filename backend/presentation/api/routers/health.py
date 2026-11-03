from dataclasses import asdict

from fastapi import APIRouter, Depends

from backend.application.ports.persistence import UnitOfWork
from backend.application.services import health as health_service
from backend.presentation.api.dependencies import ApiDependencies
from backend.presentation.api.schemas import (
    HealthResponse,
)


def create_router(dependencies: ApiDependencies) -> APIRouter:
    router = APIRouter()

    @router.get("/api/v1/health", response_model=HealthResponse, tags=["health"])
    async def health(uow: UnitOfWork = Depends(dependencies.get_uow)) -> HealthResponse:
        result = await health_service.get_health(uow, dependencies.settings.worker_poll_seconds)
        return HealthResponse(**asdict(result))

    return router
