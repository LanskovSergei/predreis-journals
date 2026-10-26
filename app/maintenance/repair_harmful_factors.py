"""Исправление записей «Водителя+» с ошибочным признаком вредных факторов «absent».

До исправления событие с `harmful_factors_detected = null` превращалось в «отсутствуют», то есть в
значение, которого Предрейс не передавал. Находим такие записи по сохранённым событиям
(`inbox_events`) и возвращаем «не определялся» (NULL).

Запись типа Б неизменяема (триггер БД), поэтому правка выполняется одной транзакцией с временным
отключением триггера и записью в журнал аудита. Записи, уже вошедшие в электронный журнал (тип В),
не меняются, а только перечисляются: их документы подписаны.

Запуск: `python -m app.maintenance.repair_harmful_factors` (просмотр), с `--apply` исправляет.
"""

from __future__ import annotations

import argparse
import asyncio
import uuid
from dataclasses import dataclass, field

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_sessionmaker
from app.modules.audit.service import append_audit

AFFECTED = """
SELECT m.id, m.status, m.epl_waybill_id, m.epl_title_number
FROM medical_records m
JOIN inbox_events e
  ON e.payload ->> 'waybill_id' = m.epl_waybill_id::text
 AND e.event_type = 'T' || m.epl_title_number::text
WHERE m.source = 'epl'
  AND m.harmful_factors = 'absent'
  AND (e.payload ->> 'harmful_factors_detected') IS NULL
"""


@dataclass(slots=True)
class RepairReport:
    """Итог: сколько записей затронуто и какие остались нетронутыми."""

    found: int = 0
    fixed: int = 0
    in_journal: list[uuid.UUID] = field(default_factory=list)


async def repair(session: AsyncSession, *, apply: bool) -> RepairReport:
    """Находит (и при apply=True исправляет) записи с ошибочным «absent»."""
    rows = (await session.execute(text(AFFECTED))).all()
    report = RepairReport(found=len(rows))
    fixable = [r.id for r in rows if r.status == "signed"]
    report.in_journal = [r.id for r in rows if r.status == "in_journal"]
    if not apply or not fixable:
        return report
    await session.execute(
        text("ALTER TABLE medical_records DISABLE TRIGGER trg_medical_records_immutable")
    )
    try:
        result = await session.execute(
            text("UPDATE medical_records SET harmful_factors = NULL WHERE id = ANY(:ids)"),
            {"ids": fixable},
        )
        report.fixed = getattr(result, "rowcount", 0) or 0
    finally:
        await session.execute(
            text("ALTER TABLE medical_records ENABLE TRIGGER trg_medical_records_immutable")
        )
    await append_audit(
        session,
        None,
        action="repair.harmful_factors_unknown",
        entity_type="medical",
        payload={"fixed": report.fixed, "left_in_journal": len(report.in_journal)},
    )
    await session.commit()
    return report


async def main() -> None:
    """Точка входа команды."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply", action="store_true", help="исправить (по умолчанию только показать)"
    )
    args = parser.parse_args()
    async with get_sessionmaker()() as session:
        report = await repair(session, apply=args.apply)
    mode = "исправлено" if args.apply else "будет исправлено"
    print(f"Найдено записей с ошибочным «absent»: {report.found}")
    print(f"{mode}: {report.fixed if args.apply else report.found - len(report.in_journal)}")
    if report.in_journal:
        print(f"Уже в электронных журналах (не меняются, нужен разбор): {len(report.in_journal)}")
        for rid in report.in_journal[:20]:
            print(f"  {rid}")


if __name__ == "__main__":
    asyncio.run(main())
