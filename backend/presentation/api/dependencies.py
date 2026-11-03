"""Dependencies assembled by the API composition root."""

from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Any

from backend.application.ports.persistence import UnitOfWork
from backend.config import Settings


@dataclass(frozen=True)
class ApiDependencies:
    settings: Settings
    get_uow: Callable[..., AsyncIterator[UnitOfWork]]
    bot: list[Any]
    admin: list[Any]
    bot_auth: Callable[..., Any]
    admin_auth: Callable[..., Any]
