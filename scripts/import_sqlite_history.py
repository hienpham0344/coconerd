"""Import a stopped SQLite snapshot without overwriting destination records."""

import argparse
import asyncio
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import DateTime, inspect, select
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from backend.config import Settings
from backend.infrastructure.database.models import Base, DeliveryReceiptRecord

RUNTIME_TABLES = {"api_rate_limits", "worker_heartbeats"}


def _normalize_row(table, row):
    result = dict(row)
    for column in table.columns:
        value = result.get(column.name)
        if isinstance(column.type, DateTime) and isinstance(value, datetime):
            result[column.name] = value.replace(tzinfo=UTC) if value.tzinfo is None else value
    return result


def _order_dependencies(table, rows):
    if table.name != "discord_actions":
        return rows
    pending = {row["id"]: row for row in rows}
    result = []
    while pending:
        ready = [row for row in pending.values() if row["dependency_id"] not in pending]
        if not ready:
            raise ValueError("Cyclic Discord action dependencies")
        for row in ready:
            result.append(row)
            del pending[row["id"]]
    return result


async def import_sqlite_snapshot(
    source: Path,
    destination: AsyncEngine,
    *,
    receipts_path: Path | None = None,
    dry_run: bool = False,
) -> dict[str, int]:
    source = source.resolve(strict=True)
    if (
        destination.url.drivername.startswith("sqlite")
        and Path(destination.url.database).resolve() == source
    ):
        raise ValueError("Source and destination must be different databases")
    reader = create_async_engine(f"sqlite+aiosqlite:///{source}")
    counts = {}
    try:
        async with reader.connect() as connection, destination.begin() as writer:
            names = await connection.run_sync(lambda conn: set(inspect(conn).get_table_names()))
            for table in Base.metadata.sorted_tables:
                if table.name not in names or table.name in RUNTIME_TABLES:
                    continue
                rows = [
                    _normalize_row(table, row)
                    for row in (await connection.execute(select(table))).mappings()
                ]
                for row in _order_dependencies(table, rows):
                    predicate = [column == row[column.name] for column in table.primary_key]
                    existing = (
                        (await writer.execute(select(table).where(*predicate))).mappings().first()
                    )
                    if existing is not None:
                        if _normalize_row(table, existing) != row:
                            raise ValueError(f"Conflicting destination row in {table.name}")
                    elif not dry_run:
                        await writer.execute(table.insert().values(**row))
                counts[table.name] = len(rows)
            if receipts_path is not None:
                path = receipts_path.resolve(strict=True)
                legacy = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
                try:
                    rows = legacy.execute("SELECT key, discord_id FROM receipts").fetchall()
                finally:
                    legacy.close()
                table = DeliveryReceiptRecord.__table__
                for key, value in rows:
                    existing = await writer.scalar(
                        select(table.c.discord_id).where(table.c.key == key)
                    )
                    if existing is not None and existing != value:
                        raise ValueError("Conflicting destination row in delivery_receipts")
                    if existing is None and not dry_run:
                        await writer.execute(
                            table.insert().values(
                                key=key, discord_id=value, updated_at=datetime.now(UTC)
                            )
                        )
                counts[table.name] = len(rows)
    finally:
        await reader.dispose()
    return counts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--receipts", type=Path)
    parser.add_argument(
        "--apply", action="store_true", help="Commit the import; default is read-only"
    )
    args = parser.parse_args()

    async def run():
        engine = None
        try:
            settings = Settings()
            if not settings.database_url.startswith("postgresql+asyncpg://"):
                raise ValueError("Destination must be PostgreSQL")
            engine = create_async_engine(settings.database_url, connect_args={"timeout": 10})
            counts = await import_sqlite_snapshot(
                args.source, engine, receipts_path=args.receipts, dry_run=not args.apply
            )
            for table, count in counts.items():
                print(f"{table}: {count}")
            print("Import committed" if args.apply else "Read-only preflight passed")
        except Exception as error:
            print(f"Import failed ({type(error).__name__}); no partial import was committed.")
            raise SystemExit(1) from None
        finally:
            if engine is not None:
                await engine.dispose()

    asyncio.run(run())


if __name__ == "__main__":
    main()
