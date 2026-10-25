"""Сборка ZIP-контейнера электронного журнала (документ типа 2, ТЗ стр. 21).

Два шага, как в ТЗ:
 1. «Отправить на подпись» (`build_package`): отбираются файлы записей, строится journal.xml,
    выгрузка аудита и человекочитаемый PDF для СА. Всё сохраняется в хранилище, план пакета —
    в `EJournal.package`. СА подписывает ровно тот journal.xml, который видел.
 2. «Подписать» (`finalize`): journal.xml подписывается УКЭП организации через Предрейс, PDF
    рисуется с плашкой подписи, собирается итоговый ZIP и проверяется `verify_container`.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.errors import ConflictError
from app.core.storage import Storage, get_storage
from app.domain.enums import JournalKind, RecordSource
from app.integrations.predreis.client import SignResult
from app.models.catalog import Organization
from app.models.documents import EJournal, RecordDocument
from app.models.records import AnyRecord, record_model
from app.modules.audit.service import export_audit_json
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
    Party,
    SignatureRef,
    build_journal_xml,
)
from app.modules.reports.rows import fmt_date
from app.modules.reports.service import (
    JOURNAL_TITLES,
    render_registry_pdf,
    render_single_record_pdf,
)
from app.modules.signing.xml_builder import build_record_xml
from app.xmlschemas import FORMAT_VERSION

logger = logging.getLogger(__name__)

GENERATOR = "predreis-journals/0.1.0"
JOURNAL_XML = "journal.xml"


class PackageBuilder(Protocol):
    """Интерфейс строителя контейнера (реальный и тестовые заглушки)."""

    async def build_package(self, journal: EJournal, records: Sequence[AnyRecord]) -> None:
        """Готовит пакет при отправке журнала на подпись."""

    async def finalize(self, journal: EJournal, result: SignResult) -> None:
        """Собирает итоговый ZIP из готовой подписи journal.xml."""

    def discard(self, journal: EJournal) -> list[str]:
        """Сбрасывает подготовленный пакет; возвращает ключи файлов для удаления после коммита."""

    async def delete_files(self, keys: Sequence[str]) -> None:
        """Удаляет файлы из хранилища (сбой не критичен)."""


@dataclass(frozen=True, slots=True)
class PlanEntry:
    """Файл будущего контейнера: путь в архиве и расположение в хранилище."""

    path: str
    role: str
    key: str
    sha256: str
    size: int
    record_id: str | None = None
    signed_file: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Сериализация для JSONB."""
        return asdict(self)

    @staticmethod
    def from_dict(data: dict[str, Any]) -> PlanEntry:
        """Десериализация из JSONB."""
        return PlanEntry(**data)


class ContainerBuilder:
    """Реальный строитель контейнера журнала."""

    def __init__(
        self,
        session: AsyncSession,
        storage: Storage | None = None,
        settings: Settings | None = None,
    ) -> None:
        """Принимает сессию БД, хранилище файлов и настройки."""
        self.session = session
        self.storage = storage or get_storage()
        self.settings = settings or get_settings()

    # --- вспомогательное ---------------------------------------------------------------------
    async def _read_checked(self, key: str, expected_sha: str | None, what: str) -> bytes:
        """Читает файл из хранилища и сверяет контрольную сумму (защита от подмены на диске)."""
        try:
            data = await self.storage.get(key)
        except OSError as exc:
            raise ConflictError(
                f"Файл недоступен в хранилище: {what}", code="storage_integrity"
            ) from exc
        if expected_sha and sha256_hex(data) != expected_sha:
            raise ConflictError(
                f"Контрольная сумма файла не совпадает с зафиксированной: {what}",
                code="storage_integrity",
            )
        return data

    async def _documents(self, journal: EJournal) -> dict[uuid.UUID, RecordDocument]:
        """Электронные документы (подписи) записей журнала."""
        model = record_model(journal.kind)
        rows = await self.session.execute(
            select(RecordDocument)
            .join(model, model.id == RecordDocument.record_id)
            .where(
                RecordDocument.record_kind == journal.kind,
                model.reserved_journal_id == journal.id,
            )
        )
        return {d.record_id: d for d in rows.scalars()}

    async def _records(self, journal: EJournal) -> list[AnyRecord]:
        """Записи журнала в хронологическом порядке."""
        model: Any = record_model(journal.kind)
        rows = await self.session.execute(
            select(model)
            .where(model.reserved_journal_id == journal.id)
            .order_by(model.performed_at, model.id)
        )
        records: list[AnyRecord] = list(rows.scalars().all())
        return records

    @staticmethod
    def _period(journal: EJournal) -> tuple[str, str]:
        """Период журнала в формате ДД.ММ.ГГГГ."""
        return journal.period_from.strftime("%d.%m.%Y"), journal.period_to.strftime("%d.%m.%Y")

    @staticmethod
    def _customer(org: Organization) -> dict[str, Any]:
        """Реквизиты заказчика для PDF."""
        return {"name": org.short_name or org.name, "inn": org.inn, "address": org.legal_address}

    async def _organization(self, journal: EJournal) -> Organization:
        """Организация журнала."""
        org = await self.session.get(Organization, journal.organization_id)
        if org is None:
            raise ConflictError("Организация журнала не найдена", code="organization_missing")
        return org

    # --- шаг 1: отправка на подпись ----------------------------------------------------------
    async def build_package(self, journal: EJournal, records: Sequence[AnyRecord]) -> None:
        """Готовит пакет: файлы записей, journal.xml, выгрузку аудита и PDF для СА."""
        kind = journal.kind
        org = await self._organization(journal)
        docs = await self._documents(journal)
        base = f"journals/{journal.id}"
        plan: list[PlanEntry] = []
        refs: list[JournalRecordRef] = []

        for rec in sorted(records, key=lambda r: (r.performed_at, str(r.id))):
            doc = docs.get(rec.id)
            rid = str(rec.id)
            prefix = f"records/{rid}"
            is_epl = rec.source is RecordSource.EPL
            if is_epl:
                xml = build_record_xml(kind, rec)
                xml_key = await self.storage.put(f"{base}/epl/{rid}/record.xml", xml)
                pdf = await render_single_record_pdf(kind, rec, doc)
                pdf_key = await self.storage.put(f"{base}/epl/{rid}/record.pdf", pdf)
            else:
                if doc is None or not doc.xml_key:
                    raise ConflictError(
                        f"У записи {rid} нет электронного документа", code="document_missing"
                    )
                xml = await self._read_checked(doc.xml_key, doc.xml_sha256, f"{rid}/record.xml")
                xml_key = doc.xml_key
                pdf = (
                    await self._read_checked(doc.pdf_key, doc.pdf_sha256, f"{rid}/record.pdf")
                    if doc.pdf_key
                    else b""
                )
                pdf_key = doc.pdf_key or ""

            xml_ref = FileRef(f"{prefix}/record.xml", sha256_hex(xml))
            plan.append(
                PlanEntry(xml_ref.path, "record-xml", xml_key, xml_ref.sha256, len(xml), rid)
            )
            pdf_ref = None
            if pdf:
                pdf_ref = FileRef(f"{prefix}/record.pdf", sha256_hex(pdf))
                plan.append(
                    PlanEntry(pdf_ref.path, "record-pdf", pdf_key, pdf_ref.sha256, len(pdf), rid)
                )

            sig_ref: SignatureRef | None = None
            tsp_ref: FileRef | None = None
            if doc is not None and doc.sig_key:
                if not doc.cert_serial or not doc.cert_subject:
                    raise ConflictError(
                        f"У подписи записи {rid} нет данных сертификата",
                        code="signature_meta_missing",
                    )
                sig = await self._read_checked(doc.sig_key, None, f"{rid}/подпись")
                name = "epl-title" if is_epl else "record.xml"
                sig_path = f"{prefix}/{name}.sig"
                sig_ref = SignatureRef(
                    sig_path, sha256_hex(sig), doc.cert_serial, doc.cert_subject
                )
                plan.append(
                    PlanEntry(
                        sig_path,
                        "record-signature",
                        doc.sig_key,
                        sig_ref.sha256,
                        len(sig),
                        rid,
                        None if is_epl else xml_ref.path,
                    )
                )
                if doc.tsp_key:
                    tsp = await self._read_checked(doc.tsp_key, None, f"{rid}/метка времени")
                    tsp_path = f"{prefix}/{name}.tsp"
                    tsp_ref = FileRef(tsp_path, sha256_hex(tsp))
                    plan.append(
                        PlanEntry(
                            tsp_path,
                            "record-timestamp",
                            doc.tsp_key,
                            tsp_ref.sha256,
                            len(tsp),
                            rid,
                            sig_path,
                        )
                    )
            refs.append(
                JournalRecordRef(
                    record_id=rec.id,
                    source=rec.source,
                    performed_at=rec.performed_at,
                    result=rec.result,
                    xml=xml_ref,
                    pdf=pdf_ref,
                    signature=sig_ref,
                    timestamp=tsp_ref,
                )
            )

        audit = await export_audit_json(
            self.session, [str(r.id) for r in records] + [str(journal.id)]
        )
        audit_key = await self.storage.put(f"{base}/audit-log.json", audit.data)
        audit_sha = sha256_hex(audit.data)
        plan.append(
            PlanEntry("audit/audit-log.json", "audit-log", audit_key, audit_sha, len(audit.data))
        )

        issuer = Party(self.settings.executor_inn, self.settings.executor_name)
        journal_xml = build_journal_xml(
            journal_id=journal.id,
            kind=kind,
            issuer=issuer,
            organization=Party(org.inn, org.name),
            period_from=journal.period_from,
            period_to=journal.period_to,
            created_at=datetime.now(timezone.utc),
            audit=AuditRef("audit/audit-log.json", audit_sha, audit.entries, audit.chain_head),
            records=refs,
        )
        xml_key = await self.storage.put(f"{base}/{JOURNAL_XML}", journal_xml)
        xml_sha = sha256_hex(journal_xml)
        plan.append(PlanEntry(JOURNAL_XML, "journal-xml", xml_key, xml_sha, len(journal_xml)))

        period_from, period_to = self._period(journal)
        preview = await render_registry_pdf(
            kind=kind,
            customer=self._customer(org),
            records=list(records),
            docs=docs,
            period_from=period_from,
            period_to=period_to,
            title=JOURNAL_TITLES[kind],
        )
        journal.preview_pdf_key = await self.storage.put(f"{base}/journal-preview.pdf", preview)
        journal.xml_key = xml_key
        journal.xml_sha256 = xml_sha
        journal.audit_key = audit_key
        journal.package = [e.to_dict() for e in plan]
        journal.record_count = len(records)

    # --- шаг 2: подпись СА -------------------------------------------------------------------
    async def finalize(self, journal: EJournal, result: SignResult) -> None:
        """Собирает итоговый ZIP из готовой подписи journal.xml (УКЭП организации)."""
        if not journal.package or not journal.xml_key or not journal.xml_sha256:
            raise ConflictError("Пакет журнала не подготовлен", code="package_missing")
        plan = [PlanEntry.from_dict(d) for d in journal.package]
        files: list[ContainerFile] = []
        journal_xml = b""
        for e in plan:
            data = await self._read_checked(e.key, e.sha256, e.path)
            files.append(
                ContainerFile(
                    e.path,
                    e.role,
                    data,
                    uuid.UUID(e.record_id) if e.record_id else None,
                    e.signed_file,
                )
            )
            if e.role == "journal-xml":
                journal_xml = data
        if sha256_hex(journal_xml) != journal.xml_sha256:
            raise ConflictError("journal.xml изменился после отправки", code="storage_integrity")

        cert = result.certificate
        if cert is None:
            raise ConflictError(
                "В подписи журнала нет сведений о сертификате", code="signature_meta_missing"
            )
        org = await self._organization(journal)
        records = await self._records(journal)
        docs = await self._documents(journal)
        period_from, period_to = self._period(journal)
        pdf = await render_registry_pdf(
            kind=journal.kind,
            customer=self._customer(org),
            records=records,
            docs=docs,
            period_from=period_from,
            period_to=period_to,
            title=JOURNAL_TITLES[journal.kind],
            stamp={
                "serial": cert.serial,
                "subject": cert.subject,
                "valid_from": fmt_date(cert.valid_from),
                "valid_to": fmt_date(cert.valid_to),
            },
        )
        created = datetime.now(timezone.utc)
        readme = render_readme(
            kind_title=JOURNAL_TITLES[journal.kind],
            org_name=org.name,
            org_inn=org.inn,
            period_from=period_from,
            period_to=period_to,
            count=len(records),
            journal_id=journal.id,
            created_at=created,
            format_version=FORMAT_VERSION,
            issuer_name=self.settings.executor_name,
            issuer_inn=self.settings.executor_inn,
        )
        files += [
            ContainerFile(
                "journal.xml.sig", "journal-signature", result.signature, signed_file=JOURNAL_XML
            ),
            ContainerFile("journal.pdf", "journal-pdf", pdf),
            ContainerFile("README.txt", "readme", readme),
        ]
        if result.tsp:
            files.append(
                ContainerFile(
                    "journal.xml.tsp",
                    "journal-timestamp",
                    result.tsp,
                    signed_file="journal.xml.sig",
                )
            )
        zip_bytes, _ = build_zip(
            files, container_id=journal.id, created_at=created, generator=GENERATOR
        )
        problems = verify_container(zip_bytes)
        if problems:
            logger.error("Собранный контейнер %s не прошёл проверку: %s", journal.id, problems[:5])
            raise ConflictError(
                "Собранный контейнер не прошёл самопроверку",
                code="container_invalid",
                details=problems[:20],
            )

        base = f"journals/{journal.id}"
        journal.sig_key = await self.storage.put(f"{base}/journal.xml.sig", result.signature)
        if result.tsp:
            journal.tsp_key = await self.storage.put(f"{base}/journal.xml.tsp", result.tsp)
        journal.pdf_key = await self.storage.put(f"{base}/journal.pdf", pdf)
        journal.zip_key = await self.storage.put(f"{base}/journal.zip", zip_bytes)
        journal.zip_sha256 = sha256_hex(zip_bytes)
        journal.cert_serial = cert.serial
        journal.cert_subject = cert.subject
        journal.cert_valid_from = cert.valid_from
        journal.cert_valid_to = cert.valid_to
        journal.ocsp_status = result.ocsp_status

    # --- отклонение --------------------------------------------------------------------------
    def discard(self, journal: EJournal) -> list[str]:
        """Расформировывает пакет: сбрасывает поля и возвращает ключи созданных журналом файлов."""
        prefix = f"journals/{journal.id}/"
        keys = [
            e["key"] for e in (journal.package or []) if str(e.get("key", "")).startswith(prefix)
        ]
        if journal.preview_pdf_key:
            keys.append(journal.preview_pdf_key)
        journal.package = None
        journal.preview_pdf_key = None
        journal.xml_key = None
        journal.xml_sha256 = None
        journal.audit_key = None
        return keys

    async def delete_files(self, keys: Sequence[str]) -> None:
        """Удаляет файлы после коммита; сбой хранилища только логируется."""
        for key in keys:
            try:
                await self.storage.delete(key)
            except OSError as exc:
                logger.warning("Не удалось удалить файл %s: %s", key, exc)


_ = JournalKind  # вид журнала используется в аннотациях и словарях заголовков
