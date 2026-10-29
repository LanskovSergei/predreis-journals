"""Сборка и независимая проверка ZIP-контейнера электронного журнала (чистая логика, без БД)."""

from __future__ import annotations

import hashlib
import io
import uuid
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from lxml import etree

from app.core.errors import ValidationFailedError
from app.modules.ejournal.xml_builder import ManifestFile, build_manifest_xml, safe_archive_path
from app.xmlschemas import NS_JOURNAL, NS_MANIFEST, NS_RECORD, safe_fromstring, validate_xml

MANIFEST_PATH = "manifest.xml"
MAX_FILES = 500_000
MAX_TOTAL_BYTES = 4 * 1024**3
MAX_FILE_BYTES = 512 * 1024**2
_ZIP_EPOCH = (2020, 1, 1, 0, 0, 0)


def sha256_hex(data: bytes) -> str:
    """SHA-256 в виде 64 строчных hex-символов."""
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True, slots=True)
class ContainerFile:
    """Файл контейнера: путь, назначение, содержимое и связи для манифеста."""

    path: str
    role: str
    data: bytes
    record_id: uuid.UUID | None = None
    signed_file: str | None = None


def build_zip(
    files: Sequence[ContainerFile],
    *,
    container_id: uuid.UUID,
    created_at: datetime,
    generator: str,
) -> tuple[bytes, bytes]:
    """Собирает ZIP с манифестом. Возвращает (zip, manifest.xml). Вывод детерминирован."""
    seen: set[str] = set()
    for f in files:
        safe_archive_path(f.path)
        if f.path == MANIFEST_PATH or f.path in seen:
            raise ValidationFailedError(
                f"Недопустимый или повторный путь: {f.path}", code="path_clash"
            )
        seen.add(f.path)
    manifest = build_manifest_xml(
        container_id=container_id,
        created_at=created_at,
        generator=generator,
        files=[
            ManifestFile(
                path=f.path,
                role=f.role,
                size=len(f.data),
                sha256=sha256_hex(f.data),
                record_id=f.record_id,
                signed_file=f.signed_file,
            )
            for f in files
        ],
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for path, data in sorted([(f.path, f.data) for f in files] + [(MANIFEST_PATH, manifest)]):
            info = zipfile.ZipInfo(path, date_time=_ZIP_EPOCH)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            z.writestr(info, data)
    return buf.getvalue(), manifest


def _q(ns: str, tag: str) -> str:
    """Имя элемента в пространстве имён."""
    return f"{{{ns}}}{tag}"


def verify_container(data: bytes) -> list[str]:
    """Проверяет целостность контейнера. Пустой список — всё в порядке.

    Проверяется: безопасность архива, манифест (XSD, состав, размеры, SHA-256), journal.xml (XSD,
    ссылки на файлы и их хеши, число записей, audit log) и каждый record.xml (XSD, id).
    Криптографическую проверку подписей (.sig) выполняет СКЗИ (КриптоПро), см. README контейнера.
    """
    errors: list[str] = []
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        return ["Файл не является корректным ZIP-архивом"]
    infos = z.infolist()
    if len(infos) > MAX_FILES or sum(i.file_size for i in infos) > MAX_TOTAL_BYTES:
        return ["Архив слишком большой (защита от zip-бомбы)"]
    names = [i.filename for i in infos]
    if len(set(names)) != len(names):
        errors.append("В архиве есть файлы с одинаковыми путями")
    for info in infos:
        try:
            safe_archive_path(info.filename)
        except ValidationFailedError:
            errors.append(f"Небезопасный путь в архиве: {info.filename!r}")
        if info.file_size > MAX_FILE_BYTES:
            errors.append(f"Файл слишком большой: {info.filename}")
    if errors:
        return errors
    if MANIFEST_PATH not in names:
        return ["В архиве нет manifest.xml"]

    manifest_bytes = z.read(MANIFEST_PATH)
    schema_errors = validate_xml(manifest_bytes, "manifest")
    if schema_errors:
        return [f"manifest.xml: {e}" for e in schema_errors]
    manifest = safe_fromstring(manifest_bytes)
    entries = {f.get("path", ""): f for f in manifest.iter(_q(NS_MANIFEST, "File"))}

    for path in names:
        if path != MANIFEST_PATH and path not in entries:
            errors.append(f"Файл не описан в манифесте: {path}")
    contents: dict[str, bytes] = {}
    for path, entry in entries.items():
        if path not in names:
            errors.append(f"Файл из манифеста отсутствует в архиве: {path}")
            continue
        blob = z.read(path)
        contents[path] = blob
        if len(blob) != int(entry.get("size", "-1")):
            errors.append(f"Размер не совпадает с манифестом: {path}")
        if sha256_hex(blob) != entry.get("sha256"):
            errors.append(f"Контрольная сумма не совпадает с манифестом: {path}")
        signed = entry.get("signedFile")
        if signed and signed not in entries:
            errors.append(f"signedFile ссылается на отсутствующий файл: {path} -> {signed}")
    if errors:
        return errors

    roles = {
        f.get("role"): path
        for path, f in entries.items()
        if f.get("role", "").startswith("journal-")
    }
    journal_path = roles.get("journal-xml")
    if journal_path is None:
        return ["В манифесте нет journal.xml"]
    journal_errors = validate_xml(contents[journal_path], "journal")
    if journal_errors:
        return [f"{journal_path}: {e}" for e in journal_errors]
    errors += _verify_journal(contents[journal_path], entries, contents)
    sig_path = roles.get("journal-signature")
    if sig_path is None:
        errors.append("Нет подписи journal.xml")
    elif entries[sig_path].get("signedFile") != journal_path:
        errors.append("Подпись журнала не связана с journal.xml")
    return errors


def _verify_journal(
    journal_xml: bytes, entries: dict[str, etree._Element], contents: dict[str, bytes]
) -> list[str]:
    """Сверяет ссылки journal.xml с файлами контейнера и проверяет записи по XSD."""
    errors: list[str] = []
    root = safe_fromstring(journal_xml)
    records = root.find(_q(NS_JOURNAL, "Records"))
    if not (records is not None):  # явная проверка: assert исчезает при python -O
        raise RuntimeError("Нарушено внутреннее условие")
    items = records.findall(_q(NS_JOURNAL, "Record"))
    if int(records.get("count", "-1")) != len(items):
        errors.append("Records/@count не равен числу записей")

    def check_ref(ref: etree._Element, what: str) -> str | None:
        """Проверяет, что файл по ссылке есть в манифесте с тем же хешем."""
        path, sha = ref.get("path", ""), ref.get("sha256")
        entry = entries.get(path)
        if entry is None:
            errors.append(f"{what}: нет файла {path}")
            return None
        if entry.get("sha256") != sha:
            errors.append(f"{what}: хеш в journal.xml не совпадает с файлом {path}")
        return path

    audit = root.find(_q(NS_JOURNAL, "AuditLog"))
    if audit is not None:
        check_ref(audit, "AuditLog")
    for item in items:
        rid = item.get("id", "")
        for tag in ("Xml", "Pdf", "Signature", "Timestamp"):
            ref = item.find(_q(NS_JOURNAL, tag))
            if ref is not None:
                check_ref(ref, f"запись {rid} / {tag}")
        xml_ref = item.find(_q(NS_JOURNAL, "Xml"))
        path = xml_ref.get("path", "") if xml_ref is not None else ""
        if path in contents:
            rec_errors = validate_xml(contents[path], "record")
            errors += [f"{path}: {e}" for e in rec_errors]
            if not rec_errors and safe_fromstring(contents[path]).get("id") != rid:
                errors.append(f"{path}: id записи не совпадает с journal.xml")
    return errors


README_TEMPLATE = """ЭЛЕКТРОННЫЙ ЖУРНАЛ {kind_title}
================================================================

Организация:   {org_name} (ИНН {org_inn})
Период:        {period_from} - {period_to}
Записей:       {count}
Идентификатор: {journal_id}
Сформирован:   {created_at}
Формат:        контейнер {format_version}, схемы XSD версии {format_version}
Издатель:      {issuer_name} (ИНН {issuer_inn})

СОСТАВ
------
manifest.xml           реестр всех файлов: размер, SHA-256, назначение, связь подписей с файлами
journal.xml            машиночитаемый журнал: перечень записей и ссылки на их файлы
journal.xml.sig        откреплённая УКЭП организации на journal.xml
journal.xml.tsp        метка доверенного времени к подписи journal.xml (если выдана)
journal.pdf            человекочитаемая версия журнала (сведения, составляющие врачебную
                       тайну, скрыты; на последней странице - плашка о подписи)
records/<id>/record.xml      запись (машиночитаемая)
records/<id>/record.pdf      запись (человекочитаемая)
records/<id>/record.xml.sig  откреплённая УКЭП специалиста на record.xml
records/<id>/record.xml.tsp  метка доверенного времени к подписи специалиста
records/<id>/epl-title.sig   для записей из ЭПЛ: подпись титула ЭПЛ (если передана),
                             она подписывает титул, а не record.xml
audit/audit-log.json   выгрузка журнала аудита по записям журнала на момент отправки журнала
                       на подпись (последующие события в неё не входят)
README.txt             этот файл

ПОРЯДОК ПРОВЕРКИ
----------------
1. Сверьте размеры и SHA-256 всех файлов с manifest.xml.
2. Проверьте journal.xml по схеме journal.xsd, а каждый record.xml - по record.xsd
   (urn:predreis:journals:journal:1.0 и urn:predreis:journals:record:1.0).
3. Убедитесь, что SHA-256 файлов, указанные в journal.xml, совпадают с фактическими.
4. Проверьте откреплённую подпись journal.xml.sig относительно journal.xml (КриптоПро CSP,
   cryptcp или иное СКЗИ с поддержкой ГОСТ Р 34.10-2012), включая цепочку сертификата,
   срок действия на момент подписания и статус отзыва.
5. Для каждой записи проверьте record.xml.sig относительно record.xml.
6. Хеш audit/audit-log.json указан в подписанном journal.xml. Для каждой записи аудита
   SHA-256(prev_hash + JSON тела записи) должен давать значение hash
   (тело: ts, actor_id, actor_role, ip, session_id, action, entity_type, entity_id, payload;
   JSON с сортировкой ключей, разделители «,» и «:», без ASCII-экранирования).
   Выгрузка содержит подмножество глобальной цепочки: каждая запись самодостаточна для
   пересчёта хеша, полная цепочка хранится в системе.

Сведения, составляющие врачебную тайну (ст. 13 323-ФЗ), содержатся в record.xml.
Распространять контейнер можно только лицам, имеющим на это право.
"""


def render_readme(
    *,
    kind_title: str,
    org_name: str,
    org_inn: str,
    period_from: str,
    period_to: str,
    count: int,
    journal_id: uuid.UUID,
    created_at: datetime,
    format_version: str,
    issuer_name: str,
    issuer_inn: str,
) -> bytes:
    """Формирует README.txt контейнера."""
    text = README_TEMPLATE.format(
        kind_title=kind_title,
        org_name=org_name,
        org_inn=org_inn,
        period_from=period_from,
        period_to=period_to,
        count=count,
        journal_id=journal_id,
        created_at=created_at.isoformat(),
        format_version=format_version,
        issuer_name=issuer_name,
        issuer_inn=issuer_inn,
    )
    return text.encode("utf-8")


_ = NS_RECORD  # пространство имён записи используется схемами при проверке record.xml
