"""Дозаполнение подписей титулов ЭПЛ у уже принятых записей.

До 18.11.2026 платформа не передавала в событиях подпись титула, поэтому у записей из ЭПЛ нет
файла подписи и данных сертификата (серийный номер, владелец, срок) — в PDF они пустые. Подписи
хранятся на платформе (`waybill_titles.ecp_signature`); их выгружают в файл JSON Lines
(`{"waybill_id": ..., "title_number": 2|3|6, "signature_b64": ...}`), а этот модуль сохраняет
подпись к документу записи и заполняет из неё сведения о сертификате.

Меняются только документы без файла подписи; поля сертификата, если уже заполнены, не трогаются.
Сами записи (тип Б неизменяем) не меняются.

Запуск: `python -m app.maintenance.backfill_title_signatures FILE` (просмотр),
с `--apply` записывает.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import binascii
import json
import logging
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_sessionmaker
from app.core.storage import Storage, get_storage
from app.domain.enums import JournalKind
from app.integrations.predreis.cms import extract_cert_info
from app.integrations.predreis.signature import is_placeholder
from app.models.documents import RecordDocument
from app.models.records import MedicalRecord, TechnicalRecord
from app.modules.audit.service import append_audit

logger = logging.getLogger(__name__)

TitleKey = tuple[uuid.UUID, int]


@dataclass(slots=True)
class BackfillReport:
    """Итог дозаполнения."""

    without_signature: int = 0
    matched: int = 0
    with_certificate: int = 0
    placeholders: int = 0
    broken: int = 0
    no_title_on_platform: int = 0


def read_signatures(lines: Iterable[str]) -> dict[TitleKey, str]:
    """Читает выгрузку подписей с платформы (JSON Lines).

    Args:
        lines: Строки файла; пустые пропускаются.

    Returns:
        Подпись в base64 по паре (рейс, номер титула).
    """
    result: dict[TitleKey, str] = {}
    for line in lines:
        if not line.strip():
            continue
        item = json.loads(line)
        if item.get("signature_b64"):
            key = (uuid.UUID(str(item["waybill_id"])), int(item["title_number"]))
            result[key] = str(item["signature_b64"])
    return result


def _decode(value: str) -> bytes | None:
    """Base64 подписи КриптоПро (с переносами строк) → байты; None, если это не base64."""
    try:
        return base64.b64decode("".join(value.split()), validate=True)
    except (binascii.Error, ValueError):
        return None


async def backfill(
    session: AsyncSession,
    storage: Storage,
    signatures: dict[TitleKey, str],
    *,
    apply: bool,
) -> BackfillReport:
    """Сохраняет подписи титулов к документам записей из ЭПЛ и заполняет данные сертификата.

    Args:
        session: Сессия БД журналов.
        storage: Хранилище файлов документов.
        signatures: Подписи по паре (рейс, номер титула).
        apply: False — только посчитать, ничего не меняя.

    Returns:
        Сколько документов найдено, сопоставлено и заполнено.
    """
    report = BackfillReport()
    for kind, model in (
        (JournalKind.MEDICAL, MedicalRecord),
        (JournalKind.TECHNICAL, TechnicalRecord),
    ):
        rows = (
            await session.execute(
                select(RecordDocument, model.epl_waybill_id, model.epl_title_number)
                .join(model, model.id == RecordDocument.record_id)
                .where(
                    RecordDocument.record_kind == kind,
                    RecordDocument.sig_key.is_(None),
                    model.epl_waybill_id.is_not(None),
                )
            )
        ).all()
        for doc, waybill_id, title_number in rows:
            report.without_signature += 1
            found = waybill_id is not None and title_number is not None
            value = signatures.get((waybill_id, title_number)) if found else None  # type: ignore[arg-type]
            if value is None:
                report.no_title_on_platform += 1
                continue
            if is_placeholder(value):
                report.placeholders += 1
                continue
            signature = _decode(value)
            if signature is None:
                report.broken += 1
                continue
            report.matched += 1
            cert = extract_cert_info(signature)
            if cert is not None:
                report.with_certificate += 1
            if not apply:
                continue
            doc.sig_key = await storage.put(
                f"records/{kind.value}/{doc.record_id}/epl.sig", signature
            )
            if cert is not None:
                doc.cert_serial = doc.cert_serial or cert.serial
                doc.cert_subject = doc.cert_subject or cert.subject
                doc.cert_valid_from = doc.cert_valid_from or cert.valid_from
                doc.cert_valid_to = doc.cert_valid_to or cert.valid_to
    if apply and report.matched:
        await append_audit(
            session,
            None,
            action="repair.epl_title_signatures",
            entity_type="record_document",
            payload={"matched": report.matched, "with_certificate": report.with_certificate},
        )
        await session.commit()
    return report


async def main() -> None:
    """Точка входа: просмотр или запись (`--apply`)."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", type=Path, help="Выгрузка подписей с платформы (JSON Lines)")
    parser.add_argument(
        "--apply", action="store_true", help="Записать (без флага — только подсчёт)"
    )
    args = parser.parse_args()
    signatures = read_signatures(args.file.read_text("utf-8").splitlines())
    async with get_sessionmaker()() as session:
        report = await backfill(session, get_storage(), signatures, apply=args.apply)
    mode = "ЗАПИСАНО" if args.apply else "пробный прогон, ничего не изменено"
    print(
        f"подписей в выгрузке: {len(signatures)}\n"
        f"документов из ЭПЛ без подписи: {report.without_signature}\n"
        f"  найдена подпись титула: {report.matched}"
        f" (из них с сертификатом: {report.with_certificate})\n"
        f"  заглушка вместо подписи: {report.placeholders}\n"
        f"  подпись не base64: {report.broken}\n"
        f"  подписи на платформе нет: {report.no_title_on_platform}\n"
        f"{mode}"
    )


if __name__ == "__main__":
    asyncio.run(main())
