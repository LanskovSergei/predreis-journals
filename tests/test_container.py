"""Контейнер журнала: сборка детерминирована, проверка ловит подделки (юнит-тесты)."""

from __future__ import annotations

import io
import json
import uuid
import zipfile
from collections.abc import Callable
from datetime import datetime

import pytest

from app.core.errors import ValidationFailedError
from app.domain.enums import JournalKind, RecordSource
from app.modules.audit.service import compute_hash, verify_audit_export
from app.modules.ejournal.container import (
    ContainerFile,
    build_zip,
    render_readme,
    sha256_hex,
    verify_container,
)
from app.modules.ejournal.xml_builder import (
    AuditRef,
    FileRef,
    JournalRecordRef,
    ManifestFile,
    Party,
    SignatureRef,
    build_journal_xml,
    build_manifest_xml,
)
from app.modules.signing.xml_builder import build_record_xml
from tests import xml_samples as samples

CID = uuid.UUID("77777777-7777-4777-8777-777777777777")
RID = "11111111-1111-4111-8111-111111111111"
CREATED = datetime(2026, 11, 1, 9, 0, tzinfo=samples.MSK)
AUDIT = json.dumps({"format": "1.0", "entries": []}).encode()


def make_container() -> bytes:
    """Собирает согласованный контейнер: запись, подпись, аудит, журнал и его подпись."""
    xml = build_record_xml(JournalKind.MEDICAL, samples.medical())
    pdf, sig = b"%PDF-record", b"SIG-RECORD"
    prefix = f"records/{RID}"
    journal = build_journal_xml(
        journal_id=CID,
        kind=JournalKind.MEDICAL,
        issuer=Party("5027236147", "ООО «ПРЕДРЕЙС»"),
        organization=Party("7707083893", "ООО «Тест»"),
        period_from=samples.date(2026, 10, 1),
        period_to=samples.date(2026, 10, 31),
        created_at=CREATED,
        audit=AuditRef("audit/audit-log.json", sha256_hex(AUDIT), 0, "0" * 64),
        records=[
            JournalRecordRef(
                record_id=uuid.UUID(RID),
                source=RecordSource.MANUAL,
                performed_at=samples.medical().performed_at,
                result=samples.medical().result,
                xml=FileRef(f"{prefix}/record.xml", sha256_hex(xml)),
                pdf=FileRef(f"{prefix}/record.pdf", sha256_hex(pdf)),
                signature=SignatureRef(
                    f"{prefix}/record.xml.sig", sha256_hex(sig), "abc123", "Абдуллаева Г.А."
                ),
            )
        ],
    )
    readme = render_readme(
        kind_title="ТЕСТ", org_name="ООО «Тест»", org_inn="7707083893", period_from="01.10.2026",
        period_to="31.10.2026", count=1, journal_id=CID, created_at=CREATED, format_version="1.0",
        issuer_name="ООО «ПРЕДРЕЙС»", issuer_inn="5027236147",
    )  # fmt: skip
    rid = uuid.UUID(RID)
    files = [
        ContainerFile("journal.xml", "journal-xml", journal),
        ContainerFile("journal.xml.sig", "journal-signature", b"SIG-JOURNAL", signed_file="journal.xml"),
        ContainerFile("journal.pdf", "journal-pdf", b"%PDF-journal"),
        ContainerFile(f"{prefix}/record.xml", "record-xml", xml, rid),
        ContainerFile(f"{prefix}/record.pdf", "record-pdf", pdf, rid),
        ContainerFile(f"{prefix}/record.xml.sig", "record-signature", sig, rid, f"{prefix}/record.xml"),
        ContainerFile("audit/audit-log.json", "audit-log", AUDIT),
        ContainerFile("README.txt", "readme", readme),
    ]  # fmt: skip
    return build_zip(files, container_id=CID, created_at=CREATED, generator="test")[0]


def rewrite(data: bytes, change: Callable[[dict[str, bytes]], None]) -> bytes:
    """Пересобирает ZIP после правки словаря «путь → содержимое» (манифест не пересчитывается)."""
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        content = {i.filename: z.read(i.filename) for i in z.infolist()}
    change(content)
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for name, blob in content.items():
            z.writestr(zipfile.ZipInfo(name), blob)
    return out.getvalue()


def test_valid_container_passes() -> None:
    """Согласованный контейнер проходит все проверки."""
    assert verify_container(make_container()) == []


def test_build_is_deterministic() -> None:
    """Один и тот же вход даёт побайтово один ZIP."""
    assert make_container() == make_container()


@pytest.mark.parametrize(
    ("name", "change", "expected"),
    [
        ("изменён record.xml", lambda c: c.update({f"records/{RID}/record.xml": c[f"records/{RID}/record.xml"] + b" "}), "Размер не совпадает"),
        ("изменена подпись записи", lambda c: c.update({f"records/{RID}/record.xml.sig": b"FORGED-RECORD"}), "Контрольная сумма"),
        ("удалён record.pdf", lambda c: c.pop(f"records/{RID}/record.pdf"), "отсутствует в архиве"),
        ("лишний файл", lambda c: c.update({"extra.txt": b"x"}), "не описан в манифесте"),
        ("подменён journal.xml", lambda c: c.update({"journal.xml": c["journal.xml"].replace(b"7707083893", b"7707083894")}), "Контрольная сумма"),
        ("удалён manifest", lambda c: c.pop("manifest.xml"), "нет manifest.xml"),
        ("обход каталога", lambda c: c.update({"../evil.txt": b"x"}), "Небезопасный путь"),
        ("абсолютный путь", lambda c: c.update({"/etc/passwd": b"x"}), "Небезопасный путь"),
    ],
)  # fmt: skip
def test_tampering_is_detected(
    name: str, change: Callable[[dict[str, bytes]], None], expected: str
) -> None:
    """Любое изменение состава или содержимого контейнера обнаруживается."""
    errors = verify_container(rewrite(make_container(), change))
    assert errors, name
    assert any(expected in e for e in errors), (name, errors)


def test_consistent_forgery_is_caught_by_journal_xml() -> None:
    """Подмена record.xml с пересчётом манифеста ловится: хеш записан в journal.xml (он подписан)."""
    original = make_container()
    rec_path = f"records/{RID}/record.xml"

    def forge(c: dict[str, bytes]) -> None:
        """Меняет запись и честно пересчитывает manifest.xml, но journal.xml остаётся прежним."""
        c[rec_path] = c[rec_path].replace(b"<Pulse>72</Pulse>", b"<Pulse>60</Pulse>")
        m = c["manifest.xml"].decode()
        old_sha = sha256_hex(
            rewrite(original, lambda _: None) and b""
        )  # заглушка, ниже точная замена
        assert old_sha
        import re

        entry = re.search(rf'<File path="{re.escape(rec_path)}"[^>]*/>', m)
        assert entry
        new = re.sub(r'size="\d+"', f'size="{len(c[rec_path])}"', entry.group(0))
        new = re.sub(r'sha256="[0-9a-f]{64}"', f'sha256="{sha256_hex(c[rec_path])}"', new)
        c["manifest.xml"] = m.replace(entry.group(0), new).encode()

    errors = verify_container(rewrite(original, forge))
    assert any("хеш в journal.xml не совпадает" in e for e in errors), errors


def test_missing_journal_signature_is_reported() -> None:
    """Контейнер без подписи журнала не считается корректным."""
    errors = verify_container(
        rewrite(make_container(), lambda c: (c.pop("journal.xml.sig"), c.update({"manifest.xml": c["manifest.xml"].replace(b'role="journal-signature"', b'role="readme"')})))
    )  # fmt: skip
    assert errors


def test_not_a_zip() -> None:
    """Мусор вместо ZIP отклоняется без исключения."""
    assert verify_container(b"not a zip") == ["Файл не является корректным ZIP-архивом"]


def test_build_zip_rejects_bad_paths() -> None:
    """Сборка не принимает пути с «..», повторы и зарезервированное имя манифеста."""
    kwargs = {"container_id": CID, "created_at": CREATED, "generator": "t"}
    f = ContainerFile("a.txt", "readme", b"x")
    with pytest.raises(ValidationFailedError):
        build_zip([ContainerFile("../a.txt", "readme", b"x")], **kwargs)
    with pytest.raises(ValidationFailedError):
        build_zip([f, f], **kwargs)
    with pytest.raises(ValidationFailedError):
        build_zip([ContainerFile("manifest.xml", "readme", b"x")], **kwargs)


def test_manifest_xml_matches_zip_listing() -> None:
    """Манифест из build_zip совпадает с независимо построенным."""
    _, manifest = build_zip(
        [ContainerFile("README.txt", "readme", b"hello")],
        container_id=CID,
        created_at=CREATED,
        generator="t",
    )
    assert manifest == build_manifest_xml(
        container_id=CID,
        created_at=CREATED,
        generator="t",
        files=[ManifestFile("README.txt", "readme", 5, sha256_hex(b"hello"))],
    )  # fmt: skip


def test_audit_export_verification_detects_tampering() -> None:
    """Выгрузка аудита самодостаточна: подмена любого поля записи ломает её хеш."""
    prev = "0" * 64
    entries = []
    for i, action in enumerate(("record.create", "record.sign"), 1):
        body = {
            "ts": f"2026-10-14T08:2{i}:00+00:00",
            "actor_id": "u1",
            "actor_role": "medic",
            "ip": "10.0.0.1",
            "session_id": None,
            "action": action,
            "entity_type": "medical",
            "entity_id": RID,
            "payload": {"x": i},
        }
        h = compute_hash(prev, body)
        entries.append({**body, "id": i, "prev_hash": prev, "hash": h})
        prev = h
    doc = {"format": "1.0", "entries": entries}
    assert verify_audit_export(json.dumps(doc).encode()) == []
    entries[1]["actor_id"] = "attacker"
    assert verify_audit_export(json.dumps(doc).encode())
    assert verify_audit_export(b"garbage")
