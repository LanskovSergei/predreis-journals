"""Замеры производительности на заполненной базе (см. scripts/load_seed.py).

Запуск: JOURNALS_DATABASE_URL=... python scripts/bench.py
Измеряются операции, которые вызывает фронтенд, и самые тяжёлые фоновые (PDF, ZIP).
"""

from __future__ import annotations

import asyncio
import resource
import statistics
import sys
import time
import uuid
from collections.abc import Awaitable, Callable
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select, text

from app.core.db import get_sessionmaker
from app.core.security import Principal
from app.domain.enums import JournalKind, Role
from app.models.catalog import Organization, User
from app.modules.ejournal.container import ContainerFile, build_zip, verify_container
from app.modules.medical.service import MedicalService
from app.modules.records.schemas import MedicalFilters, PageParams, TechnicalFilters
from app.modules.reports.service import ExportRequest, ReportService
from app.modules.stats.service import StatsService
from app.modules.technical.service import TechnicalService

RESULTS: list[tuple[str, float, float, str]] = []


def principal(role: Role, org: uuid.UUID | None = None) -> Principal:
    """Пользователь для замеров."""
    return Principal(uuid.uuid4(), role, True, org, "Замер")


async def measure(
    name: str, fn: Callable[[], Awaitable[object]], repeat: int = 5, note: str = ""
) -> None:
    """Выполняет операцию несколько раз и запоминает медиану и максимум (мс)."""
    times: list[float] = []
    for _ in range(repeat):
        start = time.perf_counter()
        await fn()
        times.append((time.perf_counter() - start) * 1000)
    RESULTS.append((name, statistics.median(times), max(times), note))


async def main() -> None:
    """Прогоняет замеры и печатает таблицу."""
    maker = get_sessionmaker()
    manager = principal(Role.PREDREIS)
    async with maker() as s:
        org = (
            await s.execute(select(Organization).order_by(Organization.inn).limit(1))
        ).scalar_one()
        medic = (
            await s.execute(select(User).where(User.role == Role.MEDIC).limit(1))
        ).scalar_one()
        total = (await s.execute(text("select count(*) from medical_records"))).scalar_one()
    client = principal(Role.CLIENT, org.id)
    page = PageParams(1, 10)
    print(f"Записей медосмотров: {total}")

    async def listing(who: Principal, f: MedicalFilters, p: PageParams = page) -> object:
        """Список с новой сессией на вызов, как в API."""
        async with maker() as session:
            return await MedicalService(session).list_records(who, f, p)

    async def tech(f: TechnicalFilters) -> object:
        """Список техконтроля."""
        async with maker() as session:
            return await TechnicalService(session).list_records(manager, f, page)

    await measure("список, без фильтров (страница 1)", lambda: listing(manager, MedicalFilters()))
    await measure(
        "список, страница 2000 (offset 20 000)",
        lambda: listing(manager, MedicalFilters(), PageParams(2000, 10)),
    )
    month = {"date_from": date(2026, 6, 1), "date_to": date(2026, 6, 30)}
    await measure(
        "список, организация + месяц",
        lambda: listing(manager, MedicalFilters(organization_id=org.id, **month)),
    )
    await measure("список, только даты (месяц)", lambda: listing(manager, MedicalFilters(**month)))
    await measure(
        "список, ФИО (0 совпадений)",
        lambda: listing(manager, MedicalFilters(driver_name="иванов")),
    )
    await measure(
        "список, ФИО (полное, ~0,5% таблицы)",
        lambda: listing(manager, MedicalFilters(driver_name="попов михаил александрович 5")),
    )
    await measure(
        "список, ФИО (частое слово, ~10% таблицы)",
        lambda: listing(manager, MedicalFilters(driver_name="михаил")),
    )
    await measure(
        "список, «на подпись» у медика",
        lambda: listing(manager, MedicalFilters(specialist_user_id=medic.id, is_signed=False)),
    )
    await measure("список, с примечанием", lambda: listing(manager, MedicalFilters(has_note=True)))
    await measure("список клиента (своя организация)", lambda: listing(client, MedicalFilters()))
    await measure(
        "список техконтроля, госномер (полный)", lambda: tech(TechnicalFilters(plate="А005"))
    )

    async def stats() -> object:
        """Плашки стартовой страницы."""
        async with maker() as session:
            return await StatsService(session).overview(manager)

    await measure("статистика стартовой (плашки)", stats)

    async def pdf(rows_from: date, rows_to: date) -> bytes:
        """PDF-выгрузка организации за период."""
        async with maker() as session:
            data, _ = await ReportService(session).registry_pdf(
                manager,
                JournalKind.MEDICAL,
                ExportRequest(organization_id=org.id, date_from=rows_from, date_to=rows_to),
            )
            return data

    started = time.perf_counter()
    pdf_month = await pdf(date(2026, 6, 1), date(2026, 6, 30))
    RESULTS.append(
        (
            "PDF-выгрузка, организация + месяц",
            (time.perf_counter() - started) * 1000,
            0,
            f"{len(pdf_month) // 1024} КБ",
        )
    )
    started = time.perf_counter()
    big = await pdf(date(2026, 1, 1), date(2026, 7, 19))
    RESULTS.append(
        (
            "PDF-выгрузка, ~4800 строк (у предела 5000)",
            (time.perf_counter() - started) * 1000,
            0,
            f"{len(big) // 1024} КБ",
        )
    )

    # ZIP: сборка и проверка контейнера из 2000 записей (по 4 файла, как в журнале)
    files = [ContainerFile("journal.xml", "journal-xml", b"<x/>")]
    for _ in range(2000):
        rid = uuid.uuid4()
        files += [
            ContainerFile(f"records/{rid}/record.xml", "record-xml", b"x" * 3000, rid),
            ContainerFile(f"records/{rid}/record.pdf", "record-pdf", b"%PDF" + b"x" * 40_000, rid),
            ContainerFile(
                f"records/{rid}/record.xml.sig",
                "record-signature",
                b"s" * 3000,
                rid,
                f"records/{rid}/record.xml",
            ),
            ContainerFile(f"records/{rid}/record.xml.tsp", "record-timestamp", b"t" * 1500, rid),
        ]
    started = time.perf_counter()
    data, _ = build_zip(
        files, container_id=uuid.uuid4(), created_at=datetime.now(timezone.utc), generator="bench"
    )
    RESULTS.append(
        (
            "ZIP: сборка 2000 записей (8001 файл)",
            (time.perf_counter() - started) * 1000,
            0,
            f"{len(data) // 1024 // 1024} МБ",
        )
    )
    started = time.perf_counter()
    verify_container(data)
    RESULTS.append(
        (
            "ZIP: проверка (без подписи журнала)",
            (time.perf_counter() - started) * 1000,
            0,
            "ошибки ожидаемы",
        )
    )

    width = max(len(r[0]) for r in RESULTS)
    print(f"\n{'операция':{width}}  медиана, мс  макс, мс  примечание")
    for name, med, mx, note in RESULTS:
        print(f"{name:{width}}  {med:11.0f}  {mx:8.0f}  {note}")
    print(
        f"\nПик памяти процесса: {resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // 1024} МБ"
    )


if __name__ == "__main__":
    asyncio.run(main())
