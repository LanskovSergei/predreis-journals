"""Проверка целостности журнала аудита (хеш-цепочки) потоково, без загрузки таблицы в память.

Запуск: `python -m app.maintenance.verify_audit`. Код возврата: 0 — цепочка цела, 1 — нарушение.
"""

from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_sessionmaker
from app.models.audit import AuditLog
from app.modules.audit.service import GENESIS_HASH, _body, compute_hash


@dataclass(frozen=True, slots=True)
class AuditCheck:
    """Результат проверки: сколько записей прочитано и где первое нарушение."""

    checked: int
    broken_at: int | None = None
    reason: str | None = None

    @property
    def ok(self) -> bool:
        """Цепочка цела."""
        return self.broken_at is None


async def verify_stream(session: AsyncSession, batch: int = 5000) -> AuditCheck:
    """Проходит записи по порядку и сверяет связь с предыдущей и собственный хеш."""
    previous = GENESIS_HASH
    checked = 0
    stream = await session.stream_scalars(
        select(AuditLog).order_by(AuditLog.id).execution_options(yield_per=batch)
    )
    try:
        async for row in stream:
            if row.prev_hash != previous:
                return AuditCheck(checked, row.id, "prev_hash не совпадает с предыдущей записью")
            if row.hash != compute_hash(previous, _body(row)):
                return AuditCheck(checked, row.id, "хеш записи не совпадает с её содержимым")
            previous = row.hash
            checked += 1
    finally:
        await stream.close()  # иначе серверный курсор остаётся открытым в сессии
    return AuditCheck(checked)


async def main() -> int:
    """Точка входа команды."""
    async with get_sessionmaker()() as session:
        result = await verify_stream(session)
    if result.ok:
        print(f"Журнал аудита цел: проверено записей {result.checked}")
        return 0
    print(f"НАРУШЕНИЕ на записи id={result.broken_at}: {result.reason}")
    print(f"До неё проверено записей: {result.checked}")
    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
