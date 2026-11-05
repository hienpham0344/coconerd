"""Conflict inserts use the same dialect as the bound database session."""

from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession


def conflict_insert(session: AsyncSession, model):
    dialect = session.get_bind().dialect.name
    if dialect == "postgresql":
        return postgres_insert(model)
    if dialect == "sqlite":
        return sqlite_insert(model)
    raise ValueError("Unsupported database dialect")
