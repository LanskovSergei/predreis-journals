"""XML электронного журнала (journal.xml) и манифеста контейнера (manifest.xml)."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime

from lxml import etree

from app.core.errors import ValidationFailedError
from app.domain.enums import InspectionResult, JournalKind, RecordSource
from app.xmlschemas import FORMAT_VERSION, NS_JOURNAL, NS_MANIFEST, ensure_valid


def safe_archive_path(path: str) -> str:
    """Проверяет путь внутри ZIP: относительный, без «..», «\\» и пустых сегментов."""
    parts = path.split("/")
    if (
        not path
        or path.startswith("/")
        or "\\" in path
        or any(p in ("", ".", "..") for p in parts)
    ):
        raise ValidationFailedError(f"Недопустимый путь в архиве: {path!r}", code="unsafe_path")
    return path


@dataclass(frozen=True, slots=True)
class FileRef:
    """Ссылка на файл в контейнере с контрольной суммой."""

    path: str
    sha256: str


@dataclass(frozen=True, slots=True)
class SignatureRef(FileRef):
    """Ссылка на файл подписи с данными сертификата."""

    cert_serial: str
    signer: str


@dataclass(frozen=True, slots=True)
class AuditRef(FileRef):
    """Ссылка на выгрузку аудита: число записей и хеш головы глобальной цепочки."""

    entries: int
    chain_head: str


@dataclass(frozen=True, slots=True)
class JournalRecordRef:
    """Запись журнала: идентификатор, краткие данные и ссылки на файлы."""

    record_id: uuid.UUID
    source: RecordSource
    performed_at: datetime
    result: InspectionResult
    xml: FileRef
    pdf: FileRef | None = None
    signature: SignatureRef | None = None
    timestamp: FileRef | None = None


@dataclass(frozen=True, slots=True)
class Party:
    """Сторона документа: ИНН и наименование."""

    inn: str
    name: str


@dataclass(frozen=True, slots=True)
class ManifestFile:
    """Файл контейнера для манифеста."""

    path: str
    role: str
    size: int
    sha256: str
    record_id: uuid.UUID | None = None
    signed_file: str | None = None


def _q(ns: str, tag: str) -> str:
    """Имя элемента в пространстве имён."""
    return f"{{{ns}}}{tag}"


def _file_ref(parent: etree._Element, tag: str, ref: FileRef) -> etree._Element:
    """Элемент-ссылка на файл (path + sha256)."""
    el = etree.SubElement(
        parent, _q(NS_JOURNAL, tag), {"path": safe_archive_path(ref.path), "sha256": ref.sha256}
    )
    if isinstance(ref, SignatureRef):
        el.set("certSerial", ref.cert_serial)
        el.set("signer", ref.signer)
    return el


def _party(parent: etree._Element, tag: str, party: Party) -> None:
    """Блок стороны (Issuer / Organization)."""
    el = etree.SubElement(parent, _q(NS_JOURNAL, tag))
    etree.SubElement(el, _q(NS_JOURNAL, "INN")).text = party.inn
    etree.SubElement(el, _q(NS_JOURNAL, "Name")).text = party.name


def build_journal_xml(
    *,
    journal_id: uuid.UUID,
    kind: JournalKind,
    issuer: Party,
    organization: Party,
    period_from: date,
    period_to: date,
    created_at: datetime,
    audit: AuditRef,
    records: Sequence[JournalRecordRef],
) -> bytes:
    """Строит journal.xml: записи упорядочены по времени осмотра, документ проверяется по XSD."""
    root = etree.Element(
        _q(NS_JOURNAL, "ElectronicJournal"),
        {"version": FORMAT_VERSION, "id": str(journal_id), "kind": kind.value},
        nsmap={None: NS_JOURNAL},
    )
    _party(root, "Issuer", issuer)
    _party(root, "Organization", organization)
    period = etree.SubElement(root, _q(NS_JOURNAL, "Period"))
    etree.SubElement(period, _q(NS_JOURNAL, "From")).text = period_from.isoformat()
    etree.SubElement(period, _q(NS_JOURNAL, "To")).text = period_to.isoformat()
    etree.SubElement(root, _q(NS_JOURNAL, "CreatedAt")).text = created_at.isoformat()
    etree.SubElement(
        root,
        _q(NS_JOURNAL, "AuditLog"),
        {
            "path": safe_archive_path(audit.path),
            "sha256": audit.sha256,
            "entries": str(audit.entries),
            "chainHead": audit.chain_head,
        },
    )
    ordered = sorted(records, key=lambda r: (r.performed_at, str(r.record_id)))
    container = etree.SubElement(root, _q(NS_JOURNAL, "Records"), {"count": str(len(ordered))})
    for rec in ordered:
        el = etree.SubElement(
            container,
            _q(NS_JOURNAL, "Record"),
            {
                "id": str(rec.record_id),
                "source": rec.source.value,
                "performedAt": rec.performed_at.isoformat(),
                "result": rec.result.value,
            },
        )
        _file_ref(el, "Xml", rec.xml)
        if rec.pdf:
            _file_ref(el, "Pdf", rec.pdf)
        if rec.signature:
            _file_ref(el, "Signature", rec.signature)
        if rec.timestamp:
            _file_ref(el, "Timestamp", rec.timestamp)
    data = etree.tostring(root, xml_declaration=True, encoding="UTF-8", pretty_print=True)
    ensure_valid(data, "journal", code="journal_xml_invalid")
    return data


def build_manifest_xml(
    *,
    container_id: uuid.UUID,
    created_at: datetime,
    generator: str,
    files: Sequence[ManifestFile],
) -> bytes:
    """Строит manifest.xml — реестр файлов контейнера с размерами и SHA-256."""
    root = etree.Element(
        _q(NS_MANIFEST, "Manifest"),
        {
            "formatVersion": FORMAT_VERSION,
            "containerId": str(container_id),
            "createdAt": created_at.isoformat(),
            "generator": generator,
        },
        nsmap={None: NS_MANIFEST},
    )
    container = etree.SubElement(root, _q(NS_MANIFEST, "Files"))
    for f in sorted(files, key=lambda x: x.path):
        attrs = {
            "path": safe_archive_path(f.path),
            "role": f.role,
            "size": str(f.size),
            "sha256": f.sha256,
        }
        if f.record_id:
            attrs["recordId"] = str(f.record_id)
        if f.signed_file:
            attrs["signedFile"] = safe_archive_path(f.signed_file)
        etree.SubElement(container, _q(NS_MANIFEST, "File"), attrs)
    data = etree.tostring(root, xml_declaration=True, encoding="UTF-8", pretty_print=True)
    ensure_valid(data, "manifest", code="manifest_xml_invalid")
    return data
