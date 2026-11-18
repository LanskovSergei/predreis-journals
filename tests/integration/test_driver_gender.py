"""Пол водителя: платформа его часто не знает, менеджер дополняет в картотеке журналов."""

from __future__ import annotations

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.storage import LocalStorage
from app.domain.enums import Gender
from app.models.catalog import Driver
from app.models.records import MedicalRecord
from app.modules.reports.rows import medical_row
from app.modules.reports.service import ReportService
from app.workers.consumer import Outcome, process_body
from tests.factories import seed
from tests.integration.test_consumer_and_sync import body, exam_payload, factory

pytestmark = pytest.mark.asyncio


async def _set_gender(session: AsyncSession, driver_id: object, gender: Gender | None) -> None:
    """Пол водителя в картотеке журналов (как будто менеджер его указал)."""
    await session.execute(update(Driver).where(Driver.id == driver_id).values(gender=gender))
    await session.commit()


async def test_epl_record_takes_gender_from_catalog_when_platform_has_none(
    session: AsyncSession, storage: LocalStorage
) -> None:
    """Событие без пола — пол из картотеки; пол из события важнее картотеки."""
    w = await seed(session)
    await _set_gender(session, w.driver.id, Gender.FEMALE)

    payload = exam_payload(w)  # в образце с платформы gender = null
    assert (
        await process_body(body(payload, mid="no-gender"), factory(session), storage, Settings())
        is Outcome.ACK
    )
    payload2 = exam_payload(w)
    payload2["driver"]["gender"] = "M"
    assert (
        await process_body(
            body(payload2, mid="with-gender"), factory(session), storage, Settings()
        )
        is Outcome.ACK
    )

    records = (await session.execute(select(MedicalRecord))).scalars().all()
    by_wb = {str(r.epl_waybill_id): r.snapshot["driver"]["gender"] for r in records}
    assert by_wb[payload["waybill_id"]] == "F"
    assert by_wb[payload2["waybill_id"]] == "M"


async def test_export_shows_gender_added_to_catalog_after_the_record(
    session: AsyncSession, storage: LocalStorage
) -> None:
    """Запись без пола: в отчёте пол подставляется из картотеки, сама запись не меняется."""
    w = await seed(session)
    await _set_gender(session, w.driver.id, None)
    assert (
        await process_body(body(exam_payload(w), mid="old"), factory(session), storage, Settings())
        is Outcome.ACK
    )
    rec = (await session.execute(select(MedicalRecord))).scalar_one()
    assert rec.snapshot["driver"]["gender"] is None
    assert medical_row(1, rec, None)["gender"] == ""

    await _set_gender(session, w.driver.id, Gender.MALE)
    genders = await ReportService(session)._catalog_genders([rec])
    assert genders == {rec.driver_id: "M"}
    assert medical_row(1, rec, None, genders.get(rec.driver_id))["gender"] == "М"
    await session.refresh(rec)
    assert rec.snapshot["driver"]["gender"] is None, "подписанная запись не меняется"
