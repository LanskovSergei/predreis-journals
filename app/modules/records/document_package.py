"""ZIP-пакет одной подписанной записи — электронный документ типа 1 (ТЗ).

Состав повторяет то, как запись кладётся в электронный журнал:

* запись, подписанная в журналах: сохранённые при подписании `record.xml` и `record.pdf`
  (с проверкой контрольных сумм), откреплённая подпись `record.xml.sig`, метка времени `.tsp`;
* запись из ЭПЛ: `record.xml` и `record.pdf` по данным записи и подпись титула ЭПЛ `epl-title.sig`
  (сам титул хранится в ГИС ЭПД, подпись к нему, а не к record.xml);
* `README.txt` — сведения о подписи (сертификат, срок, статус отзыва, время) и порядок проверки;
* `manifest.xml` — состав пакета с размерами и SHA-256.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from app.core.errors import ConflictError
from app.core.storage import Storage
from app.domain.enums import JournalKind, RecordSource
from app.models.documents import RecordDocument
from app.models.records import AnyRecord
from app.modules.ejournal.container import ContainerFile, build_zip, sha256_hex
from app.modules.reports.service import render_single_record_pdf
from app.modules.signing.xml_builder import build_record_xml

GENERATOR = "predreis-journals: документ записи"
KIND_TITLE = {
    JournalKind.MEDICAL: "Электронная запись о медицинском осмотре водителя",
    JournalKind.TECHNICAL: (
        "Электронная запись о предрейсовом контроле технического состояния транспортного средства"
    ),
}


async def _read_checked(storage: Storage, key: str, expected_sha: str | None, what: str) -> bytes:
    """Читает файл из хранилища и сверяет контрольную сумму, зафиксированную при подписании.

    Args:
        storage: Хранилище файлов.
        key: Ключ файла.
        expected_sha: SHA-256 из документа; None — не сверять.
        what: Название файла для текста ошибки.

    Returns:
        Содержимое файла.

    Raises:
        ConflictError: Файла нет или он не совпадает с подписанным.
    """
    try:
        data = await storage.get(key)
    except OSError as exc:
        raise ConflictError(
            f"Файл недоступен в хранилище: {what}", code="storage_integrity"
        ) from exc
    if expected_sha and sha256_hex(data) != expected_sha:
        raise ConflictError(
            f"Контрольная сумма не совпадает с зафиксированной при подписании: {what}",
            code="storage_integrity",
        )
    return data


def _fmt(value: datetime | None) -> str:
    """Дата и время в UTC для README или «нет данных»."""
    return value.astimezone(timezone.utc).strftime("%d.%m.%Y %H:%M UTC") if value else "нет данных"


def _readme(kind: JournalKind, record: AnyRecord, doc: RecordDocument, sig_name: str) -> bytes:
    """Человекочитаемое описание пакета и подписи."""
    is_epl = record.source is RecordSource.EPL
    signed_object = (
        f"титул {record.epl_title_number} электронного путевого листа"
        f" (ГИС ЭПД, УИД {record.gis_uid or 'нет данных'}); подпись относится к титулу, "
        "а не к record.xml"
        if is_epl
        else "файл record.xml (откреплённая подпись CAdES)"
    )
    lines = [
        KIND_TITLE[kind],
        "",
        f"Запись: {record.id}",
        f"Источник: {'электронный путевой лист' if is_epl else 'бумажный путевой лист'}",
        f"Дата осмотра: {_fmt(record.performed_at)}",
        "",
        "Подпись",
        f"  Файл подписи: {sig_name}",
        f"  Подписан: {signed_object}",
        f"  Владелец сертификата: {doc.cert_subject or 'нет данных'}",
        f"  Серийный номер сертификата: {doc.cert_serial or 'нет данных'}",
        f"  Сертификат действует: с {_fmt(doc.cert_valid_from)} по {_fmt(doc.cert_valid_to)}",
        f"  Статус отзыва на момент подписи: {doc.ocsp_status or 'нет данных'}",
        f"  Время подписи: {_fmt(doc.signed_at)}",
        f"  Метка доверенного времени (TSP): {'есть' if doc.tsp_key else 'нет'}",
        "",
        "Состав",
        "  record.xml — машиночитаемые данные записи",
        "  record.pdf — человекочитаемая версия (медицинские показатели скрыты, 323-ФЗ)",
        f"  {sig_name} — откреплённая подпись (CMS)",
        "  manifest.xml — перечень файлов с размерами и SHA-256",
        "",
        "Проверка",
        "  1. Сверьте SHA-256 файлов с manifest.xml.",
        "  2. Проверьте подпись средством, поддерживающим ГОСТ Р 34.10-2012",
        "     (например, КриптоПро CSP: cryptcp -verify -detached).",
    ]
    return ("\n".join(lines) + "\n").encode("utf-8")


async def build_record_package(
    kind: JournalKind, record: AnyRecord, doc: RecordDocument, storage: Storage
) -> bytes:
    """Собирает ZIP электронного документа подписанной записи.

    Args:
        kind: Вид журнала.
        record: Подписанная запись (тип Б или В).
        doc: Её электронный документ с файлом подписи.
        storage: Хранилище файлов.

    Returns:
        Содержимое ZIP.

    Raises:
        ConflictError: Нет подписи или файлы в хранилище не совпадают с подписанными.
    """
    if not doc.sig_key:
        raise ConflictError("У записи нет файла подписи", code="signature_missing")
    rid = str(record.id)
    if record.source is RecordSource.EPL:
        xml = build_record_xml(kind, record)
        pdf = await render_single_record_pdf(kind, record, doc)
        sig_name, signed_file = "epl-title.sig", None
    else:
        if not doc.xml_key:
            raise ConflictError("У записи нет электронного документа", code="document_missing")
        xml = await _read_checked(storage, doc.xml_key, doc.xml_sha256, f"{rid}/record.xml")
        pdf = (
            await _read_checked(storage, doc.pdf_key, doc.pdf_sha256, f"{rid}/record.pdf")
            if doc.pdf_key
            else await render_single_record_pdf(kind, record, doc)
        )
        sig_name, signed_file = "record.xml.sig", "record.xml"
    sig = await _read_checked(storage, doc.sig_key, None, f"{rid}/подпись")
    files = [
        ContainerFile("record.xml", "record-xml", xml, record.id),
        ContainerFile("record.pdf", "record-pdf", pdf, record.id),
        ContainerFile(sig_name, "record-signature", sig, record.id, signed_file),
        ContainerFile("README.txt", "readme", _readme(kind, record, doc, sig_name)),
    ]
    if doc.tsp_key:
        tsp = await _read_checked(storage, doc.tsp_key, None, f"{rid}/метка времени")
        tsp_name = sig_name.removesuffix(".sig") + ".tsp"
        files.append(ContainerFile(tsp_name, "record-timestamp", tsp, record.id, sig_name))
    data, _manifest = build_zip(
        files,
        container_id=uuid.uuid5(uuid.NAMESPACE_URL, f"record-document:{kind.value}:{rid}"),
        created_at=doc.signed_at or datetime.now(timezone.utc),
        generator=GENERATOR,
    )
    return data
