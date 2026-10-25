"""Повторная обработка сообщений из `inbox_failures` (после синхронизации справочников, правок).

Запуск: `python -m app.workers.replay [--reason dependency_missing] [--dry-run]`.
Успешно обработанные сообщения удаляются из таблицы, остальные остаются (с актуальной причиной).
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings, get_settings
from app.core.db import get_sessionmaker
from app.core.logging import setup_logging
from app.core.storage import Storage, get_storage
from app.integrations.predreis.events import Envelope
from app.models.integration import InboxFailure
from app.workers.consumer import MAX_DEPENDENCY_ATTEMPTS, Outcome, handle_envelope

logger = logging.getLogger(__name__)
EVENT_TYPES = ("journal.medical_exam", "journal.technical_exam")


@dataclass(frozen=True, slots=True)
class ReplayReport:
    """Итог повторной обработки."""

    checked: int
    resolved: int
    still_failing: int


async def replay_failures(
    session_factory: async_sessionmaker[AsyncSession],
    storage: Storage,
    settings: Settings,
    *,
    reasons: list[str] | None = None,
    dry_run: bool = False,
) -> ReplayReport:
    """Пробует обработать сохранённые отказы заново."""
    async with session_factory() as session:
        stmt = select(InboxFailure).where(
            InboxFailure.event_type.in_(EVENT_TYPES), InboxFailure.payload.is_not(None)
        )
        if reasons:
            stmt = stmt.where(InboxFailure.reason.in_(reasons))
        rows = (await session.execute(stmt.order_by(InboxFailure.created_at))).scalars().all()
        todo = [(r.id, r.message_id, r.event_type, r.payload) for r in rows]
    resolved = 0
    for failure_id, message_id, event_type, payload in todo:
        envelope = Envelope.model_validate(
            {"id": message_id, "event_type": event_type, "payload": payload}
        )
        # Повтор по зависимости здесь — это «всё ещё не готово», а не новая очередь попыток.
        handled = await handle_envelope(
            envelope, session_factory, storage, settings, {message_id: MAX_DEPENDENCY_ATTEMPTS - 1}
        )
        if handled.failure is None and handled.outcome is Outcome.ACK:
            resolved += 1
            if not dry_run:
                async with session_factory() as session:
                    row = await session.get(InboxFailure, failure_id)
                    if row is not None:
                        await session.delete(row)
                        await session.commit()
    return ReplayReport(len(todo), resolved, len(todo) - resolved)


async def main() -> None:
    """Точка входа команды."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reason", action="append", help="только отказы с этой причиной")
    parser.add_argument("--dry-run", action="store_true", help="не удалять обработанные")
    args = parser.parse_args()
    settings = get_settings()
    setup_logging(settings.log_level)
    report = await replay_failures(
        get_sessionmaker(), get_storage(), settings, reasons=args.reason, dry_run=args.dry_run
    )
    print(
        f"Проверено: {report.checked}, обработано: {report.resolved}, "
        f"остаётся: {report.still_failing}"
    )


if __name__ == "__main__":
    asyncio.run(main())
