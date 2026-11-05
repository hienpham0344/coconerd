from backend.application.errors import NotFound
from backend.application.ports.persistence import UnitOfWork


async def get_receipt(uow: UnitOfWork, key: str) -> str:
    value = await uow.delivery_receipts.get(key)
    if value is None:
        raise NotFound("Delivery receipt not found")
    return value


async def save_receipt(uow: UnitOfWork, key: str, discord_id: str) -> None:
    await uow.delivery_receipts.put(key, discord_id)
    await uow.commit()
