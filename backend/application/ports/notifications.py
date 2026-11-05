"""Wakeup hints supplement durable queue claims; they never carry queue data."""

import asyncio
from contextlib import AbstractAsyncContextManager
from typing import Protocol


class Notifications(Protocol):
    def subscribe(self) -> AbstractAsyncContextManager[asyncio.Event]: ...
