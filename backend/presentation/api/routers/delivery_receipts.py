from typing import Annotated

from fastapi import APIRouter, Depends, Path

from backend.application.ports.persistence import UnitOfWork
from backend.application.services.delivery_receipts import get_receipt, save_receipt
from backend.presentation.api.dependencies import ApiDependencies
from backend.presentation.api.schemas import DeliveryReceiptResponse

ReceiptKey = Annotated[str, Path(min_length=1, max_length=500, pattern=r"^[A-Za-z0-9:_-]+$")]


def create_router(dependencies: ApiDependencies) -> APIRouter:
    router = APIRouter(
        prefix="/api/v1/delivery-receipts", tags=["delivery"], dependencies=dependencies.delivery
    )

    @router.get("/{key}", response_model=DeliveryReceiptResponse)
    async def get(
        key: ReceiptKey, uow: UnitOfWork = Depends(dependencies.get_uow)
    ) -> DeliveryReceiptResponse:
        return DeliveryReceiptResponse(discord_id=await get_receipt(uow, key))

    @router.put("/{key}", response_model=DeliveryReceiptResponse)
    async def put(
        key: ReceiptKey,
        body: DeliveryReceiptResponse,
        uow: UnitOfWork = Depends(dependencies.get_uow),
    ) -> DeliveryReceiptResponse:
        await save_receipt(uow, key, body.discord_id)
        return body

    return router
