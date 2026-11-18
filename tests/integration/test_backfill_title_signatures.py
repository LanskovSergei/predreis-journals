"""Дозаполнение подписей титулов ЭПЛ у записей, принятых, пока платформа их не передавала."""

from __future__ import annotations

import base64
import json

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.storage import LocalStorage
from app.maintenance.backfill_title_signatures import backfill, read_signatures
from app.models.documents import RecordDocument
from app.models.records import MedicalRecord
from app.workers.consumer import Outcome, process_body
from tests.factories import seed
from tests.integration.test_consumer_and_sync import body, exam_payload, factory
from tests.test_cms import make_signature

pytestmark = pytest.mark.asyncio


async def test_title_signature_from_platform_fills_certificate_of_old_epl_record(
    session: AsyncSession, storage: LocalStorage
) -> None:
    """Запись принята без подписи; по выгрузке с платформы появляются файл подписи и сертификат."""
    w = await seed(session)
    payload = exam_payload(w)
    payload.pop("signature_b64", None)
    assert (
        await process_body(body(payload, mid="old"), factory(session), storage, Settings())
        is Outcome.ACK
    )
    rec = (await session.execute(select(MedicalRecord))).scalar_one()
    doc = (await session.execute(select(RecordDocument))).scalar_one()
    assert doc.sig_key is None and doc.cert_serial is None

    cms_bytes, cert = make_signature()
    wrapped = base64.encodebytes(cms_bytes).decode()  # с переносами строк, как у КриптоПро
    lines = [
        json.dumps({"waybill_id": str(rec.epl_waybill_id), "title_number": rec.epl_title_number, "signature_b64": wrapped}),
        json.dumps({"waybill_id": str(rec.epl_waybill_id), "title_number": 99, "signature_b64": "AUTO_SIGNATURE"}),
    ]  # fmt: skip
    signatures = read_signatures(lines)

    dry = await backfill(session, storage, signatures, apply=False)
    assert (dry.without_signature, dry.matched, dry.with_certificate) == (1, 1, 1)
    await session.refresh(doc)
    assert doc.sig_key is None, "просмотр ничего не меняет"

    done = await backfill(session, storage, signatures, apply=True)
    assert done.matched == 1
    await session.refresh(doc)
    assert doc.cert_serial == cert.serial_number.to_bytes(16, "big").hex()
    assert doc.cert_subject == "Абдуллаева Гульзана Абутдиновна"
    assert doc.cert_valid_to is not None
    assert doc.sig_key and await storage.get(doc.sig_key) == cms_bytes

    again = await backfill(session, storage, signatures, apply=True)
    assert again.without_signature == 0, "повторный запуск не трогает заполненные документы"


async def test_placeholder_and_missing_titles_are_only_counted(
    session: AsyncSession, storage: LocalStorage
) -> None:
    """Заглушка AUTO_SIGNATURE и отсутствие подписи на платформе ничего не меняют."""
    w = await seed(session)
    payload = exam_payload(w)
    payload.pop("signature_b64", None)
    assert (
        await process_body(body(payload, mid="old2"), factory(session), storage, Settings())
        is Outcome.ACK
    )
    rec = (await session.execute(select(MedicalRecord))).scalar_one()

    missing = await backfill(session, storage, {}, apply=True)
    assert (missing.without_signature, missing.no_title_on_platform) == (1, 1)

    placeholder = {(rec.epl_waybill_id, rec.epl_title_number): "AUTO_SIGNATURE"}
    report = await backfill(session, storage, placeholder, apply=True)  # type: ignore[arg-type]
    assert report.placeholders == 1
    doc = (await session.execute(select(RecordDocument))).scalar_one()
    assert doc.sig_key is None and doc.cert_serial is None
