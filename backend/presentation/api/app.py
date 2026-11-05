import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.application.errors import Conflict, InvalidTransition, NotFound
from backend.application.ports.persistence import UnitOfWork
from backend.config import Settings, get_settings
from backend.infrastructure.database.connection import create_session_factory
from backend.infrastructure.database.notifications import (
    ACTIONS_CHANNEL,
    WakeupSignal,
    listen_for_notifications,
)
from backend.infrastructure.database.repositories.dashboard import DashboardRepository
from backend.infrastructure.database.unit_of_work import SqlAlchemyUnitOfWork
from backend.presentation.api.dependencies import ApiDependencies
from backend.presentation.api.middleware import RequestBoundaryMiddleware
from backend.presentation.api.rate_limit import rate_limit_dependency
from backend.presentation.api.routers import (
    action_events,
    actions,
    dashboard,
    delivery_receipts,
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
    action_signal = WakeupSignal()

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        listener = asyncio.create_task(
            listen_for_notifications(factory.kw["bind"], ACTIONS_CHANNEL, action_signal)
        )
        try:
            yield
        finally:
            listener.cancel()
            with suppress(asyncio.CancelledError):
                await listener
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
    app.state.action_signal = action_signal
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
        app_settings,
        get_uow,
        bot_dependencies,
        admin_dependencies,
        bot_auth,
        admin_auth,
        [Depends(bot_auth), Depends(rate_limit_dependency(factory, 600, "X-API-Key", "delivery"))],
        action_signal,
    )
    for module in (
        health,
        messages,
        topics,
        actions,
        action_events,
        delivery_receipts,
        guilds,
        model_config,
        reviews,
    ):
        app.include_router(module.create_router(dependencies))

    async def get_dashboard_repository():
        async with factory() as session:
            yield DashboardRepository(session)

    app.include_router(
        dashboard.create_router(
            get_dashboard_repository,
            [
                Depends(admin_auth),
                Depends(rate_limit_dependency(factory, 600, "X-Admin-API-Key", "dashboard")),
            ],
        )
    )
    return app


app = create_app()
