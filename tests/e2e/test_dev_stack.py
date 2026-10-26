"""Сквозная проверка на настоящих процессах: подставной Предрейс, API, воркер, потребитель, RabbitMQ.

Запуск (нужны PostgreSQL, Redis, RabbitMQ и пустая база journals_e2e):
    JOURNALS_E2E=1 pytest tests/e2e -q
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable, Iterator
from typing import Any

import httpx
import pytest

from app.modules.ejournal.container import verify_container
from tools.dev_stack import API_PORT, FAKE_PORT, DevStack

pytestmark = pytest.mark.skipif(
    os.environ.get("JOURNALS_E2E") != "1", reason="сквозной стенд: JOURNALS_E2E=1"
)
API = f"http://127.0.0.1:{API_PORT}/api/v1"
FAKE = f"http://127.0.0.1:{FAKE_PORT}"


@pytest.fixture(scope="module")
def stack() -> Iterator[DevStack]:
    """Весь стенд на время модуля."""
    s = DevStack(os.environ.get("JOURNALS_E2E_DB", "journals_e2e"), sign_delay=2.0)
    s.start()
    try:
        yield s
    finally:
        s.stop()


class Session:
    """Клиент API журналов от имени пользователя ПРЕДРЕЙСа (вход по почте и паролю)."""

    def __init__(self, role: str) -> None:
        """Входит в журналы так же, как это сделает фронтенд."""
        resp = httpx.post(
            f"{API}/auth/login", json={"email": f"{role}@example.ru", "password": "password"}
        )
        assert resp.status_code == 200, resp.text
        self.profile = resp.json()
        self.http = httpx.Client(
            base_url=API,
            headers={"Authorization": f"Bearer {resp.json()['access_token']}"},
            timeout=30,
        )

    def get(self, path: str, **kw: Any) -> httpx.Response:
        """GET."""
        return self.http.get(path, **kw)

    def post(self, path: str, **kw: Any) -> httpx.Response:
        """POST."""
        return self.http.post(path, **kw)


def eventually(check: Callable[[], Any], stack: DevStack, what: str, timeout: float = 60) -> Any:
    """Ждёт, пока check вернёт истину; иначе показывает журналы процессов."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = check()
        if value:
            return value
        time.sleep(1)
    logs = "\n".join(f"--- {n} ---\n{stack.log(n, 15)}" for n in stack.procs)
    raise AssertionError(f"Не дождались: {what}\n{logs}")


def test_login_and_access_rules(stack: DevStack) -> None:
    """Вход теми же данными, что в Предрейсе; без флага доступа и с неверным паролем — отказ."""
    sa = Session("superadmin")
    assert (
        sa.profile["user"]["role"] == "superadmin"
        and "medical:ejournal_sign" in sa.profile["permissions"]
    )
    denied = httpx.post(
        f"{API}/auth/login", json={"email": "noaccess@example.ru", "password": "password"}
    )
    # Пароль верный, но флаг «доступ к журналам» выключен: вход в ПРЕДРЕЙС есть, в журналы нельзя.
    assert denied.status_code == 403 and denied.json()["error"]["code"] == "journals_disabled"
    wrong = httpx.post(
        f"{API}/auth/login", json={"email": "medic@example.ru", "password": "wrong"}
    )
    assert wrong.status_code == 401 and wrong.json()["error"]["code"] == "invalid_credentials"
    assert httpx.get(f"{API}/me").status_code == 401


def test_catalogs_sync_then_events_become_records(stack: DevStack) -> None:
    """Воркер подтягивает справочники; события из RabbitMQ превращаются в записи типа Б."""
    manager = Session("predreis")
    eventually(
        lambda: (
            manager.get("/catalog/organizations").json()["total"] >= 2
            and manager.get("/catalog/drivers").json()["total"] >= 4
        ),
        stack,
        "справочники из Предрейса",
    )
    orgs = {o["inn"]: o for o in manager.get("/catalog/organizations").json()["items"]}
    assert orgs["770000000000"]["legal_address"] is None  # адрес ИП пуст
    drivers = {
        d["full_name"]: d for d in manager.get("/catalog/drivers?page_size=50").json()["items"]
    }
    assert drivers["Водителев Василий Васильевич"]["gender"] is None
    assert drivers["Рулева Ольга Ивановна"]["license_number"] == "9911 777888"

    published = httpx.post(
        f"{FAKE}/_dev/publish", json={"waybills": 3, "old_technical_without_time": True}
    ).json()
    assert published["published"] == 10
    eventually(
        lambda: manager.get("/medical/records").json()["total"] == 6,
        stack,
        "6 медосмотров из очереди",
    )
    eventually(
        lambda: manager.get("/technical/records").json()["total"] == 3,
        stack,
        "3 техконтроля из очереди",
    )
    items = manager.get("/medical/records?page_size=50").json()["items"]
    assert {i["status"] for i in items} == {"signed"} and {i["source"] for i in items} == {"epl"}
    assert {i["phase"] for i in items} == {"pre", "post"} and all(
        i["actions"] == [] for i in items
    )
    assert all(i["harmful_factors"] is None for i in items)  # «Водитель+»: признак не определялся

    # Старый техконтроль без времени записи не создал, но очередь не заблокирована: остальное дошло.
    assert Session("superadmin").get("/stats/overview").status_code == 200


def test_manual_record_signing_failure_and_success(stack: DevStack) -> None:
    """Подпись: отказ Предрейса, заглушка AUTO_SIGNATURE, затем успех; запись закрыта на время подписи."""
    medic = Session("medic")
    manager = Session("predreis")
    org = next(
        o
        for o in manager.get("/catalog/organizations").json()["items"]
        if o["inn"] == "7700000001"
    )
    driver = next(
        d
        for d in manager.get(f"/catalog/drivers?organization_id={org['id']}").json()["items"]
        if d["full_name"].startswith("Шофёров")
    )
    body = {
        "organization_id": org["id"], "driver_id": driver["id"], "phase": "pre",
        "performed_at": "2026-10-20T08:20:00+03:00", "bp_systolic": 120, "bp_diastolic": 80,
        "pulse": 70, "temperature": "36.6", "result": "admitted",
    }  # fmt: skip
    created = medic.post("/medical/records", json=body)
    assert created.status_code == 201, created.text
    rid = created.json()["id"]

    def state() -> dict[str, Any]:
        """Текущее состояние записи."""
        return medic.get(f"/medical/records/{rid}").json()

    # 0) у специалиста нет сертификата: настоящий отказ Предрейса с понятной причиной
    nocert = Session("nocert")
    own = nocert.post("/medical/records", json=body).json()
    nocert.post("/medical/records/sign", json={"record_ids": [own["id"]]})
    refused = eventually(
        lambda: (
            (r := nocert.get(f"/medical/records/{own['id']}").json())["signing_status"] == "failed"
            and r
        ),
        stack,
        "отказ: нет сертификата",
    )
    assert "нет сертификата" in refused["signing_error"] and refused["status"] == "unsigned"
    # 1) отказ Предрейса — запись возвращается в редактируемое состояние
    httpx.post(f"{FAKE}/_dev/sign-mode/fail")
    assert medic.post("/medical/records/sign", json={"record_ids": [rid]}).json()["signed"] == 1
    failed = eventually(
        lambda: (s := state())["signing_status"] == "failed" and s, stack, "отказ подписи"
    )
    assert (
        failed["status"] == "unsigned" and "sign" in failed["actions"] and failed["signing_error"]
    )
    # 2) заглушка вместо подписи — тоже отказ, а не «подписано»
    httpx.post(f"{FAKE}/_dev/sign-mode/placeholder")
    medic.post("/medical/records/sign", json={"record_ids": [rid]})
    eventually(
        lambda: "AUTO_SIGNATURE" in (state().get("signing_error") or ""),
        stack,
        "отказ на заглушке",
    )
    assert state()["status"] == "unsigned"
    # 3) нормальная подпись
    httpx.post(f"{FAKE}/_dev/sign-mode/normal")
    medic.post("/medical/records/sign", json={"record_ids": [rid]})
    busy = state()
    assert (
        busy["status"] == "unsigned" and busy["actions"] == []
    )  # на время подписи запись закрыта
    done = eventually(
        lambda: (s := state())["status"] == "signed" and s, stack, "успешная подпись"
    )
    assert done["signature"]["cert_serial"] and done["signature"]["cert_subject"].startswith(
        "Сидорова"
    )


def test_ejournal_end_to_end(stack: DevStack) -> None:
    """Электронный журнал: сформировать → отправить → подписать (асинхронно) → ZIP проходит проверку."""
    manager, sa, client = Session("predreis"), Session("superadmin"), Session("client")
    org = next(
        o
        for o in manager.get("/catalog/organizations").json()["items"]
        if o["inn"] == "7700000001"
    )
    period = {
        "kind": "medical",
        "organization_id": org["id"],
        "period_from": "2020-01-01",
        "period_to": "2030-12-31",
    }
    draft = manager.post("/ejournals", json=period)
    assert draft.status_code == 201, draft.text
    assert (
        draft.json()["record_count"] >= 7
    )  # 6 из очереди (организация ООО) + 1 подписанная вручную
    jid = draft.json()["id"]
    assert manager.post(f"/ejournals/{jid}/submit").json()["status"] == "awaiting_signature"
    preview = manager.get(f"/ejournals/{jid}/preview")
    assert preview.status_code == 200 and preview.content.startswith(b"%PDF")
    assert manager.post(f"/ejournals/{jid}/sign").status_code == 403

    assert sa.post(f"/ejournals/{jid}/sign").json()["status"] == "signing"
    eventually(
        lambda: sa.get(f"/ejournals/{jid}").json()["status"] == "signed",
        stack,
        "подпись журнала",
        90,
    )
    zipped = manager.get(f"/ejournals/{jid}/download")
    assert zipped.status_code == 200 and verify_container(zipped.content) == []
    assert client.get(f"/ejournals/{jid}/download").status_code == 403
    records = manager.get("/medical/records?page_size=50").json()["items"]
    by_status = {r["status"] for r in records}
    # Всё подписанное попало в журнал; запись пользователя без сертификата осталась неподписанной.
    assert by_status == {"in_journal", "unsigned"}
    unsigned = [r for r in records if r["status"] == "unsigned"]
    assert len(unsigned) == 1 and unsigned[0]["signing_status"] == "failed"

    # Клиент ЭПЛ-организации видит записи без медицинских показателей и выгружает PDF.
    seen = client.get("/medical/records?page_size=50")
    assert (
        seen.status_code == 200 and seen.json()["total"] == len(records) - 1
    )  # без неподписанной
    assert "bp_systolic" not in seen.text and "complaints" not in seen.text
    export = client.post("/exports/medical", json={})
    assert export.status_code == 200 and export.content.startswith(b"%PDF")
