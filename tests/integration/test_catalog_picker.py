"""Выбор в форме записи: медик и механик читают каталог, но только подходящие по договору организации."""

from __future__ import annotations

import pytest

from tests.http_stack import Stack
from tests.integration.test_manual_catalog import make_inn, org_body

pytestmark = pytest.mark.asyncio

ORGS = "/api/v1/catalog/organizations?page_size=100"


async def _manual_org(stack: Stack, prefix: str, contract: str, name: str) -> str:
    """Ручная организация с видом договора (создаёт менеджер)."""
    body = org_body(inn=make_inn(prefix), name=name, short_name=name, contract_type=contract)
    created = await stack.client.post(
        "/api/v1/catalog/organizations", json=body, headers=stack.auth("manager")
    )
    assert created.status_code == 201, created.text
    return str(created.json()["id"])


async def test_medic_and_mechanic_see_only_organizations_of_their_journal(stack: Stack) -> None:
    """Медику — договоры «мед» и «медтех», механику — «тех» и «медтех»; раздел «Каталог» им не открыт."""
    c = stack.client
    med = await _manual_org(stack, "770000011", "med", "Только мед")
    tech = await _manual_org(stack, "770000012", "tech", "Только тех")
    both = await _manual_org(stack, "770000013", "medtech", "Мед и тех")

    medic = {o["id"] for o in (await c.get(ORGS, headers=stack.auth("medic"))).json()["items"]}
    mechanic = {
        o["id"] for o in (await c.get(ORGS, headers=stack.auth("mechanic"))).json()["items"]
    }
    assert {med, both} <= medic and tech not in medic
    assert {tech, both} <= mechanic and med not in mechanic

    # водители и ТС для выбора — тоже только по подходящим организациям
    drivers = await c.get(
        f"/api/v1/catalog/drivers?organization_id={tech}", headers=stack.auth("medic")
    )
    assert drivers.status_code == 200 and drivers.json()["items"] == []


async def test_inactive_organization_is_not_offered_and_client_has_no_catalog(
    stack: Stack,
) -> None:
    """Неактивную организацию в форме не предлагаем; клиенту каталог по-прежнему закрыт."""
    c = stack.client
    org = await _manual_org(stack, "770000014", "medtech", "Закрывается")
    patched = await c.patch(
        f"/api/v1/catalog/organizations/{org}",
        json={"is_active": False},
        headers=stack.auth("manager"),
    )
    assert patched.status_code == 200, patched.text
    medic = {o["id"] for o in (await c.get(ORGS, headers=stack.auth("medic"))).json()["items"]}
    assert org not in medic
    denied = await c.get(ORGS, headers=stack.auth("client"))
    assert denied.status_code == 403
