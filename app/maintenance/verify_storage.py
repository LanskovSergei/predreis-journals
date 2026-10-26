"""Сверка файлов хранилища с базой данных (после восстановления из копии и по расписанию).

БД хранит ключи и контрольные суммы файлов подписанных документов; сами файлы лежат в каталоге
хранилища. Команда находит отсутствующие и изменённые файлы, чтобы заметить расхождение копии БД и
копии файлов или порчу диска. Проверяются: XML и PDF записей (SHA-256), наличие подписи и
метки времени, файлы электронных журналов (SHA-256 ZIP, наличие XML, PDF и подписи).

Запуск: `python -m app.maintenance.verify_storage [--sample N] [--limit-report N]`; код возврата 1,
если найдены расхождения.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import sys
from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_sessionmaker
from app.core.storage import Storage, get_storage
from app.models.documents import EJournal, RecordDocument


@dataclass(slots=True)
class StorageReport:
    """Итог сверки: сколько проверено, что отсутствует и что изменено."""

    documents: int = 0
    journals: int = 0
    files: int = 0
    missing: list[str] = field(default_factory=list)
    corrupted: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """Расхождений нет."""
        return not self.missing and not self.corrupted


async def _check(
    storage: Storage, report: StorageReport, owner: str, key: str | None, sha: str | None
) -> None:
    """Проверяет один файл: наличие и, если известна, контрольную сумму."""
    if not key:
        return
    report.files += 1
    try:
        data = await storage.get(key)
    except OSError:
        report.missing.append(f"{owner}: нет файла {key}")
        return
    if sha and hashlib.sha256(data).hexdigest() != sha:
        report.corrupted.append(f"{owner}: изменён файл {key}")


async def verify_storage(
    session: AsyncSession, storage: Storage, *, sample: int | None = None
) -> StorageReport:
    """Сверяет документы записей и электронные журналы с файлами (sample — случайная выборка)."""
    report = StorageReport()
    docs = select(RecordDocument).order_by(func.random() if sample else RecordDocument.created_at)
    if sample:
        docs = docs.limit(sample)
    stream = await session.stream_scalars(docs.execution_options(yield_per=500))
    try:
        async for doc in stream:
            report.documents += 1
            owner = f"запись {doc.record_kind.value}/{doc.record_id}"
            await _check(storage, report, owner, doc.xml_key, doc.xml_sha256)
            await _check(storage, report, owner, doc.pdf_key, doc.pdf_sha256)
            await _check(storage, report, owner, doc.sig_key, None)
            await _check(storage, report, owner, doc.tsp_key, None)
    finally:
        await stream.close()
    journals = select(EJournal).where(EJournal.zip_key.is_not(None))
    for journal in (await session.execute(journals)).scalars():
        report.journals += 1
        owner = f"журнал {journal.id}"
        await _check(storage, report, owner, journal.zip_key, journal.zip_sha256)
        await _check(storage, report, owner, journal.xml_key, journal.xml_sha256)
        await _check(storage, report, owner, journal.pdf_key, None)
        await _check(storage, report, owner, journal.sig_key, None)
    return report


async def main() -> int:
    """Точка входа команды."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", type=int, help="проверить случайные N документов (быстро)")
    parser.add_argument(
        "--limit-report", type=int, default=20, help="сколько расхождений показать"
    )
    args = parser.parse_args()
    async with get_sessionmaker()() as session:
        report = await verify_storage(session, get_storage(), sample=args.sample)
    print(f"Проверено: документов {report.documents}, журналов {report.journals}")
    print(f"Всего файлов: {report.files}")
    for line in (report.missing + report.corrupted)[: args.limit_report]:
        print("  ", line)
    if report.ok:
        print("Расхождений нет")
        return 0
    print(f"РАСХОЖДЕНИЯ: отсутствует {len(report.missing)}, изменено {len(report.corrupted)}")
    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
