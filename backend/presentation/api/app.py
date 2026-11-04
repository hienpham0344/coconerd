from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.application.errors import Conflict, InvalidTransition, NotFound
from backend.application.ports.persistence import UnitOfWork
from backend.config import Settings, get_settings
from backend.infrastructure.database.connection import create_session_factory
from backend.infrastructure.database.unit_of_work import SqlAlchemyUnitOfWork
from backend.presentation.api.dependencies import ApiDependencies
from backend.presentation.api.middleware import RequestBoundaryMiddleware
from backend.presentation.api.rate_limit import rate_limit_dependency
from backend.presentation.api.routers import (
    actions,
    guilds,
    health,
    messages,
    model_config,
    reviews,
    topics,
)
from backend.presentation.api.security import admin_key_dependency, bot_key_dependency


def create_app(
    settings: Settings | None = None,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> FastAPI:
    app_settings = settings or get_settings()
    factory = session_factory or create_session_factory(app_settings)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        yield
        await factory.kw["bind"].dispose()

    app = FastAPI(
        title="Discord Autonomous Conversation Organizer API",
        version="1.0.0",
        description="Durable API contract between the Discord bot and the conversation backend.",
        lifespan=lifespan,
    )

    async def business_error_handler(_request: Request, exc: Exception) -> JSONResponse:
        code = 404 if isinstance(exc, NotFound) else 409 if isinstance(exc, Conflict) else 422
        return JSONResponse(status_code=code, content={"detail": str(exc)})

    for error_type in (NotFound, Conflict, InvalidTransition):
        app.add_exception_handler(error_type, business_error_handler)

    app.state.settings = app_settings
    app.state.session_factory = factory
    app.state.worker_status = "not_started_in_api_process"
    if app_settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=app_settings.cors_origins,
            allow_methods=["GET", "POST", "PUT", "DELETE"],
            allow_headers=["X-API-Key", "X-Admin-API-Key", "Content-Type"],
        )

    app.add_middleware(RequestBoundaryMiddleware, max_request_bytes=app_settings.max_request_bytes)

    async def get_uow() -> AsyncIterator[UnitOfWork]:
        async with factory() as session:
            yield SqlAlchemyUnitOfWork(session)

    bot_auth = bot_key_dependency(app_settings.bot_api_key)
    admin_auth = admin_key_dependency(app_settings.admin_api_key)
    bot_dependencies = [Depends(bot_auth), Depends(rate_limit_dependency(factory, 120))]
    admin_dependencies = [
        Depends(admin_auth),
        Depends(rate_limit_dependency(factory, 60, "X-Admin-API-Key")),
    ]

    dependencies = ApiDependencies(
        app_settings, get_uow, bot_dependencies, admin_dependencies, bot_auth, admin_auth
    )
    for module in (health, messages, topics, actions, guilds, model_config, reviews):
        app.include_router(module.create_router(dependencies))
    return app


app = create_app()
