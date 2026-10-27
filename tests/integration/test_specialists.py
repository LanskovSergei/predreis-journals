"""Сертификаты и специалисты через HTTP (формат ответа Предрейса предположительный, см. certificates.py)."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.core.errors import UpstreamError
from app.modules.specialists.service import clear_cache
from tests.http_stack import WHEN, Stack, medical_body
from tests.integration.test_frontend_contract import _signed

pytestmark = pytest.mark.asyncio


def cert(
    user_id: uuid.UUID, name: str, role: str, *, valid: bool = True, **over: object
) -> dict[str, object]:
    """Элемент ответа Предрейса; при valid=False все данные сертификата пусты, как у 22 записей из 29."""
    base: dict[str, object] = {
        "user_id": str(user_id),
        "full_name": name,
        "role": role,
        "owner": name if valid else None,
        "thumbprint": "AB12" if valid else None,
        "serial": "0x0F18DD73747ECCC4AB0D2B1EE00D4040" if valid else None,
        "issuer": "УЦ" if valid else None,
        "valid_from": "2025-09-17T00:00:00+00:00" if valid else None,
        "valid_to": (datetime.now(timezone.utc) + timedelta(days=200)).isoformat()
        if valid
        else None,
        "is_valid": valid,
    }
    return base | over


@pytest.fixture(autouse=True)
def _fresh_cache() -> None:
    """Кэш сертификатов процесса не должен переходить между тестами."""
    clear_cache()


async def test_specialist_sees_own_certificate(stack: Stack) -> None:
    """Стартовая страница медика и механика: свои сертификаты со статусом и сроком (ТЗ, стр. 9)."""
    w = stack.world
    stack.predreis.certificates = [
        cert(w.medic.id, "Сидорова Анна", "medic"),
        cert(w.mechanic.id, "Механиков Дмитрий", "mechanic", valid=False),
    ]
    mine = await stack.client.get("/api/v1/me/certificates", headers=stack.auth("medic"))
    assert mine.status_code == 200
    data = mine.json()
    assert data["status"] == "active" and data["valid_to"] and data["revocation_checked"] is False
    assert [c["serial"] for c in data["certificates"]] == ["0f18dd73747eccc4ab0d2b1ee00d4040"]
    assert (
        data["certificates"][0]["issuer"] == "УЦ"
        and data["certificates"][0]["expiring_soon"] is False
    )

    other = (
        await stack.client.get("/api/v1/me/certificates", headers=stack.auth("mechanic"))
    ).json()
    assert (
        other["status"] == "missing" and other["valid_to"] is None
    )  # в хранилище КриптоПро сертификата нет
    assert (
        other["certificates"][0]["serial"] is None
        and other["certificates"][0]["status"] == "missing"
    )


async def test_my_certificates_only_for_specialists(stack: Stack) -> None:
    """Менеджеры и клиенты своих сертификатов в журналах не смотрят."""
    for who in ("manager", "sa", "client"):
        resp = await stack.client.get("/api/v1/me/certificates", headers=stack.auth(who))
        assert resp.status_code == 403 and resp.json()["error"]["code"] == "permission_denied"
    assert (await stack.client.get("/api/v1/me/certificates")).status_code == 401


async def test_specialists_list_for_managers_without_counters(stack: Stack) -> None:
    """Плашки сертификатов у Предрейс и Админа: статус и срок каждого медика, но без счётчиков записей."""
    w = stack.world
    ghost = uuid.uuid4()  # есть в Предрейсе, в журналах не появлялся
    stack.predreis.certificates = [
        cert(w.medic.id, "Сидорова Анна", "medic"),
        cert(ghost, "Безсертова Светлана", "medic", valid=False),
        cert(w.mechanic.id, "Механиков Дмитрий", "mechanic"),
    ]
    for who in ("manager", "admin"):
        listed = await stack.client.get("/api/v1/specialists?role=medic", headers=stack.auth(who))
        assert listed.status_code == 200 and listed.json()["certificates_available"] is True
        items = {i["user_id"]: i for i in listed.json()["items"]}
        assert set(items) >= {str(w.medic.id), str(ghost)}
        assert str(w.mechanic.id) not in items  # механик в списке медиков не нужен
        assert items[str(w.medic.id)]["status"] == "active" and items[str(w.medic.id)]["valid_to"]
        assert (
            items[str(ghost)]["status"] == "missing"
            and items[str(ghost)]["certificates"][0]["serial"] is None
        )
        assert all(
            i["records"] is None for i in items.values()
        )  # счётчики только у СА (ТЗ, стр. 17)

    names = [
        i["full_name"]
        for i in (
            await stack.client.get("/api/v1/specialists", headers=stack.auth("manager"))
        ).json()["items"]
    ]
    assert names == sorted(names, key=str.lower)  # по алфавиту: удобно для фильтра «ФИО медика»


async def test_super_admin_sees_personal_counters(stack: Stack) -> None:
    """СА: рядом с сертификатом персональные счётчики «на подпись / подписанных / всего» по каждому специалисту."""
    w, c = stack.world, stack.client
    stack.predreis.certificates = [cert(w.medic.id, "Сидорова Анна", "medic")]
    await _signed(stack)
    await _signed(stack, performed_at=(WHEN + timedelta(hours=1)).isoformat())
    await c.post(
        "/api/v1/medical/records",
        json=medical_body(w, performed_at=(WHEN + timedelta(hours=2)).isoformat()),
        headers=stack.auth("medic"),
    )

    sa = (await c.get("/api/v1/specialists?role=medic", headers=stack.auth("sa"))).json()
    medic = next(i for i in sa["items"] if i["user_id"] == str(w.medic.id))
    assert medic["records"] == {"to_sign": 1, "signed": 2, "total": 3}

    stack.predreis.certificates = [cert(w.mechanic.id, "Механиков Дмитрий", "mechanic")]
    clear_cache()
    mech = (await c.get("/api/v1/specialists?role=mechanic", headers=stack.auth("sa"))).json()
    assert next(i for i in mech["items"] if i["user_id"] == str(w.mechanic.id))["records"] == {
        "to_sign": 0,
        "signed": 0,
        "total": 0,
    }


async def test_specialists_permissions(stack: Stack) -> None:
    """Список специалистов только для менеджерских ролей."""
    for who in ("medic", "mechanic", "client"):
        resp = await stack.client.get("/api/v1/specialists?role=medic", headers=stack.auth(who))
        assert resp.status_code == 403, who
    assert (
        await stack.client.get("/api/v1/specialists?role=driver", headers=stack.auth("manager"))
    ).status_code == 422


async def test_list_survives_when_predreis_is_down(stack: Stack) -> None:
    """Предрейс не ответил: специалисты и счётчики показываются, сертификаты помечены недоступными."""
    w = stack.world
    stack.predreis.certificates_error = UpstreamError("Предрейс недоступен")
    await _signed(stack)
    resp = await stack.client.get("/api/v1/specialists?role=medic", headers=stack.auth("sa"))
    assert resp.status_code == 200 and resp.json()["certificates_available"] is False
    medic = next(i for i in resp.json()["items"] if i["user_id"] == str(w.medic.id))
    assert (
        medic["status"] == "missing"
        and medic["certificates"] == []
        and medic["records"]["signed"] == 1
    )
    # свои сертификаты без Предрейса показать нельзя: это честная ошибка интеграции
    own = await stack.client.get("/api/v1/me/certificates", headers=stack.auth("medic"))
    assert own.status_code == 502


async def test_certificates_are_cached_between_requests(stack: Stack) -> None:
    """Повторные открытия страницы не нагружают Предрейс: ответ кэшируется на минуту."""
    w = stack.world
    stack.predreis.certificates = [cert(w.medic.id, "Сидорова Анна", "medic")]
    for _ in range(3):
        await stack.client.get("/api/v1/specialists?role=medic", headers=stack.auth("manager"))
    assert stack.predreis.certificate_calls == 1
    await stack.client.get(
        "/api/v1/me/certificates", headers=stack.auth("medic")
    )  # другой отбор: новый запрос
    assert stack.predreis.certificate_calls == 2
