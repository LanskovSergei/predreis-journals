"""Выгрузка подписанной записи: ZIP электронного документа типа 1 (XML + PDF + подпись + README)."""

from __future__ import annotations

import base64
import hashlib
import io
import zipfile

import pytest
from lxml import etree
from sqlalchemy import select

from app.core.config import Settings
from app.models.records import MedicalRecord
from app.workers.consumer import Outcome, process_body
from tests.http_stack import Stack
from tests.integration.test_consumer_and_sync import body, exam_payload
from tests.integration.test_frontend_contract import _signed
from tests.test_cms import make_signature

pytestmark = pytest.mark.asyncio


def _unzip(data: bytes) -> dict[str, bytes]:
    """Содержимое ZIP по именам файлов."""
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        return {name: z.read(name) for name in z.namelist()}


def _manifest_hashes(manifest: bytes) -> dict[str, str]:
    """SHA-256 из manifest.xml по путям файлов."""
    root = etree.fromstring(manifest)
    return {el.get("path"): el.get("sha256") for el in root.iter() if el.get("sha256")}


async def test_signed_paper_record_downloads_as_document(stack: Stack) -> None:
    """Запись, подписанная в журналах: тот же XML, что подписан, подпись к нему, PDF и манифест."""
    c = stack.client
    rid = await _signed(stack)
    state = (await c.get(f"/api/v1/medical/records/{rid}", headers=stack.auth("medic"))).json()
    assert state["document_available"] is True and "download" not in state["actions"]

    resp = await c.get(f"/api/v1/medical/records/{rid}/document", headers=stack.auth("manager"))
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"] == "application/zip"
    assert "medosmotr-" in resp.headers["content-disposition"]
    files = _unzip(resp.content)
    # метку времени (TSP) тестовая платформа выдаёт вместе с подписью
    assert set(files) == {
        "record.xml",
        "record.pdf",
        "record.xml.sig",
        "record.xml.tsp",
        "README.txt",
        "manifest.xml",
    }
    assert files["record.pdf"].startswith(b"%PDF")
    hashes = _manifest_hashes(files["manifest.xml"])
    for name in ("record.xml", "record.pdf", "record.xml.sig", "record.xml.tsp", "README.txt"):
        assert hashes[name] == hashlib.sha256(files[name]).hexdigest(), name
    readme = files["README.txt"].decode()
    assert "record.xml.sig" in readme and "бумажный путевой лист" in readme


async def test_epl_record_document_has_title_signature(stack: Stack) -> None:
    """Запись из ЭПЛ: XML по данным записи и подпись титула ЭПЛ со сведениями о сертификате."""
    cms_bytes, _cert = make_signature()
    payload = exam_payload(stack.world, signature_b64=base64.b64encode(cms_bytes).decode())
    async with stack.sessions() as session:
        outcome = await process_body(
            body(payload, mid="doc-epl"), stack.sessions, stack.storage, Settings()
        )
        assert outcome is Outcome.ACK
        rec = (
            await session.execute(
                select(MedicalRecord).where(MedicalRecord.epl_waybill_id == payload["waybill_id"])
            )
        ).scalar_one()
    resp = await stack.client.get(
        f"/api/v1/medical/records/{rec.id}/document", headers=stack.auth("manager")
    )
    assert resp.status_code == 200, resp.text
    files = _unzip(resp.content)
    assert files["epl-title.sig"] == cms_bytes
    assert "record.xml" in files and "record.xml.sig" not in files
    readme = files["README.txt"].decode()
    assert "Абдуллаева Гульзана Абутдиновна" in readme and "титул 2" in readme


async def test_document_rules(stack: Stack) -> None:
    """Неподписанную нельзя; клиенту медосмотр нельзя (медданные в XML), техконтроль — можно."""
    c = stack.client
    w = stack.world
    from tests.http_stack import medical_body

    draft = await c.post(
        "/api/v1/medical/records", json=medical_body(w), headers=stack.auth("medic")
    )
    did = draft.json()["id"]
    assert draft.json()["document_available"] is False
    unsigned = await c.get(
        f"/api/v1/medical/records/{did}/document", headers=stack.auth("manager")
    )
    assert unsigned.status_code == 409 and unsigned.json()["error"]["code"] == "not_signed"

    med = await _signed(stack, performed_at="2026-10-14T09:00:00+03:00")
    denied = await c.get(f"/api/v1/medical/records/{med}/document", headers=stack.auth("client"))
    assert denied.status_code == 403

    tech = await _signed(stack, kind="technical", who="mechanic")
    ok = await c.get(f"/api/v1/technical/records/{tech}/document", headers=stack.auth("client"))
    assert ok.status_code == 200, ok.text
    assert "tehkontrol-" in ok.headers["content-disposition"]
