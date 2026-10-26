"""Наблюдаемость: идентификатор запроса, заголовки, журнал обращений, метрики и их защита."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.observability import RequestIdFilter, clean_request_id, request_id_var
from app.domain.enums import SignJobStatus, SignTarget
from app.models.documents import SignJob
from app.models.integration import InboxFailure
from tests.http_stack import Stack, medical_body

pytestmark = pytest.mark.asyncio


def test_request_id_validation() -> None:
    """Входящий идентификатор принимается только безопасным, иначе создаётся новый."""
    assert clean_request_id("abc12345-DEF_6.7") == "abc12345-DEF_6.7"
    for bad in (
        None,
        "",
        "short",
        "x" * 65,
        "с кириллицей!",
        "id with spaces",
        "a;b\r\nSet-Cookie: x",
    ):
        generated = clean_request_id(bad)
        assert generated != bad and len(generated) == 32


def test_route_template_keeps_prefix_and_hides_values() -> None:
    """Шаблон: префикс из реального пути, параметры — именами; без маршрута — unmatched."""
    from types import SimpleNamespace

    from app.core.observability import route_template

    scope = {
        "path": "/api/v1/records/SOMETHING-INVALID/6ec2c894/signed",
        "route": SimpleNamespace(path="/records/{kind}/{record_id}/signed"),
    }
    assert route_template(scope) == "/api/v1/records/{kind}/{record_id}/signed"  # type: ignore[arg-type]
    assert route_template({"path": "/anything", "route": None}) == "unmatched"  # type: ignore[arg-type]
    assert route_template({"path": "/x"}) == "unmatched"  # type: ignore[arg-type]


def test_log_filter_adds_request_id() -> None:
    """Фильтр дописывает идентификатор текущего запроса в запись журнала."""
    token = request_id_var.set("req-12345678")
    try:
        record = logging.LogRecord("x", logging.INFO, "f", 1, "m", None, None)
        assert RequestIdFilter().filter(record) and record.request_id == "req-12345678"  # type: ignore[attr-defined]
    finally:
        request_id_var.reset(token)


async def test_response_headers_and_request_id(stack: Stack) -> None:
    """Заголовки безопасности; идентификатор запроса возвращается и подхватывается из запроса."""
    resp = await stack.client.get(
        "/api/v1/me", headers=stack.auth("medic") | {"X-Request-ID": "client-req-0001"}
    )
    assert resp.headers["x-request-id"] == "client-req-0001"
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert resp.headers["referrer-policy"] == "no-referrer"
    assert (
        resp.headers["cache-control"] == "no-store"
    )  # ответы API с персональными данными не кэшируются
    own = await stack.client.get("/api/v1/me", headers=stack.auth("medic"))
    assert len(own.headers["x-request-id"]) == 32
    health = await stack.client.get("/health")
    assert "cache-control" not in health.headers and health.headers["x-request-id"]


async def test_access_log_has_route_template_and_no_personal_data(
    stack: Stack,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """В журнале обращений шаблон маршрута и идентификатор, но нет строки запроса (фамилии водителей)."""
    created = await stack.client.post(
        "/api/v1/medical/records", json=medical_body(stack.world), headers=stack.auth("medic")
    )
    rid = created.json()["id"]
    with caplog.at_level(logging.INFO, logger="journals.access"):
        await stack.client.get(
            f"/api/v1/medical/records/{rid}?driver_name=Секретов",
            headers=stack.auth("medic") | {"X-Request-ID": "trace-00000001"},
        )
        await stack.client.get("/health")
    lines = [r.getMessage() for r in caplog.records if r.name == "journals.access"]
    assert any(
        "GET /api/v1/medical/records/{record_id} -> 200" in m and "[trace-00000001]" in m
        for m in lines
    )
    assert not any(
        "Секретов" in m or rid in m for m in lines
    )  # ни запрос, ни идентификатор записи
    assert not any("/health" in m for m in lines)  # пробы живости журнал не засоряют


async def test_metrics_disabled_without_token_and_protected_with_it(
    stack: Stack,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Без настроенного токена метод скрыт (404); с токеном — только по Bearer."""
    assert (await stack.client.get("/metrics")).status_code == 404
    monkeypatch.setenv("JOURNALS_METRICS_TOKEN", "scrape-secret")
    get_settings.cache_clear()
    try:
        assert (await stack.client.get("/metrics")).status_code == 401
        wrong = await stack.client.get("/metrics", headers={"Authorization": "Bearer nope"})
        assert wrong.status_code == 401
        ok = await stack.client.get("/metrics", headers={"Authorization": "Bearer scrape-secret"})
        assert ok.status_code == 200 and ok.headers["content-type"].startswith("text/plain")
    finally:
        get_settings.cache_clear()


async def test_metrics_content(stack: Stack, monkeypatch: pytest.MonkeyPatch) -> None:
    """Метрики HTTP по шаблонам маршрутов и показатели интеграции из БД; персональных данных нет."""
    monkeypatch.setenv("JOURNALS_METRICS_TOKEN", "scrape-secret")
    get_settings.cache_clear()
    try:
        created = await stack.client.post(
            "/api/v1/medical/records", json=medical_body(stack.world), headers=stack.auth("medic")
        )
        rid = created.json()["id"]
        await stack.client.get(
            f"/api/v1/medical/records/{rid}?driver_name=Секретов", headers=stack.auth("medic")
        )
        async with stack.sessions() as session:
            await _seed_integration_state(session)
        body = (
            await stack.client.get("/metrics", headers={"Authorization": "Bearer scrape-secret"})
        ).text
    finally:
        get_settings.cache_clear()
    assert (
        'journals_http_request_seconds_count{method="GET",route="/api/v1/medical/records/{record_id}",status="200"}'
        in body
    )
    assert rid not in body and "Секретов" not in body  # метки — шаблоны, а не реальные пути
    assert 'journals_sign_jobs{status="queued"} 1.0' in body
    assert 'journals_sign_jobs{status="failed"} 2.0' in body
    assert 'journals_inbox_failures{reason="exam_time_missing"} 3.0' in body
    assert "# TYPE journals_ejournals gauge" in body
    oldest = next(
        line
        for line in body.splitlines()
        if line.startswith("journals_sign_job_oldest_active_age_seconds")
    )
    assert (
        7000 < float(oldest.split()[-1]) < 7300
    )  # старейшая активная задача создана ~2 часа назад
    assert "journals_inbox_last_processed_age_seconds" in body


async def _seed_integration_state(session: AsyncSession) -> None:
    """Задачи подписи и отказы очереди для проверки показателей."""
    now = datetime.now(timezone.utc)
    base = {
        "target": SignTarget.RECORD,
        "journal_kind": "medical",
        "signer_user_id": uuid.uuid4(),
        "requested_by": uuid.uuid4(),
        "document_type": "journal.medical_exam",
        "content_key": "k",
        "content_sha256": "0" * 64,
    }
    for status, age in (
        (SignJobStatus.QUEUED, 2),
        (SignJobStatus.FAILED, 5),
        (SignJobStatus.FAILED, 6),
    ):
        job = SignJob(id=uuid.uuid4(), subject_id=uuid.uuid4(), status=status, **base)  # type: ignore[arg-type]
        job.external_id = str(job.id)
        job.created_at = now - timedelta(hours=age)
        session.add(job)
    for n in range(3):
        session.add(
            InboxFailure(
                message_id=f"m{n}", event_type="journal.technical_exam", reason="exam_time_missing"
            )
        )
    await session.commit()
