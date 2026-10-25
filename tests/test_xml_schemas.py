"""XSD электронных документов: образцы валидны, нарушения отклоняются, XXE и пути безопасны."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest
from lxml import etree

from app.core.errors import ValidationFailedError
from app.domain.enums import JournalKind, RecordSource
from app.modules.ejournal.xml_builder import (
    AuditRef,
    FileRef,
    JournalRecordRef,
    ManifestFile,
    Party,
    build_journal_xml,
    build_manifest_xml,
    safe_archive_path,
)
from app.modules.signing.xml_builder import build_record_xml
from app.xmlschemas import NS_RECORD, XmlInvalidError, validate_xml
from tests import xml_samples as samples

NS = {"r": NS_RECORD}
EXAMPLES = Path(__file__).resolve().parents[1] / "docs" / "examples"


def _mutate(data: bytes, fn: Callable[[etree._Element], None]) -> bytes:
    """Применяет правку к XML и возвращает результат."""
    root = etree.fromstring(data)
    fn(root)
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8")


def _set(path: str, value: str) -> Callable[[etree._Element], None]:
    """Правка: заменить текст первого элемента по XPath."""

    def apply(root: etree._Element) -> None:
        """Устанавливает текст."""
        root.xpath(path, namespaces=NS)[0].text = value

    return apply


def _remove(path: str) -> Callable[[etree._Element], None]:
    """Правка: удалить первый элемент по XPath."""

    def apply(root: etree._Element) -> None:
        """Удаляет элемент."""
        el = root.xpath(path, namespaces=NS)[0]
        el.getparent().remove(el)

    return apply


def test_all_samples_are_valid() -> None:
    """Образцы всех видов документов проходят проверку по своей схеме."""
    ex = samples.all_examples()
    for name in ("record-medical.xml", "record-medical-epl.xml", "record-technical.xml"):
        assert validate_xml(ex[name], "record") == [], name
    assert validate_xml(ex["journal.xml"], "journal") == []
    assert validate_xml(ex["manifest.xml"], "manifest") == []


def test_committed_examples_are_valid_and_fresh() -> None:
    """Файлы docs/examples валидны и совпадают с текущим генератором (python scripts/gen_examples.py)."""
    for name, data in samples.all_examples().items():
        path = EXAMPLES / name
        assert path.exists(), f"нет {path}: запустите scripts/gen_examples.py"
        assert path.read_bytes() == data, f"{name} устарел: запустите scripts/gen_examples.py"


def test_epl_record_has_waybill_and_note() -> None:
    """Запись из ЭПЛ содержит блок Waybill и примечание; ручная — нет."""
    epl = build_record_xml(JournalKind.MEDICAL, samples.medical(RecordSource.EPL))
    manual = build_record_xml(JournalKind.MEDICAL, samples.medical())
    assert b"<Waybill>" in epl and b"<GisUid>7f1c1f0a" in epl and b"Title>T2<" in epl
    assert b"<Note>" in epl
    assert b"<Waybill>" not in manual and b"<Note>" not in manual


def test_harmful_factors_are_optional_for_automatic_exams() -> None:
    """У автоматического осмотра «Водителя+» признака вредных факторов нет — элемент опускается."""
    data = build_record_xml(JournalKind.MEDICAL, samples.medical(harmful_factors=None))
    assert b"<HarmfulFactors>" not in data
    assert validate_xml(data, "record") == []
    # Если признак определён, он обязан быть корректным значением.
    with_flag = build_record_xml(JournalKind.MEDICAL, samples.medical())
    assert b"<HarmfulFactors>absent</HarmfulFactors>" in with_flag


def test_technical_without_driver_is_valid() -> None:
    """Водитель в техконтроле необязателен."""
    snap = {k: v for k, v in samples.SNAPSHOT.items() if k != "driver"}
    data = build_record_xml(JournalKind.TECHNICAL, samples.technical(snapshot=snap))
    assert b"<Driver>" not in data


def test_builder_is_deterministic() -> None:
    """Один и тот же вход даёт побайтово одинаковый XML (важно для подписи и хешей)."""
    a = build_record_xml(JournalKind.MEDICAL, samples.medical())
    b = build_record_xml(JournalKind.MEDICAL, samples.medical())
    assert a == b


def test_decimal_formats_do_not_break_schema() -> None:
    """Температура и алкоголь без хвостовых нулей и экспоненты остаются валидными."""
    rec = samples.medical(temperature=Decimal("37"), alcohol_mgl=Decimal("0E-2"))
    data = build_record_xml(JournalKind.MEDICAL, rec)
    assert b"<Temperature>37</Temperature>" in data
    assert b"<Alcohol>0.00</Alcohol>" in data


@pytest.mark.parametrize(
    ("name", "mutation"),
    [
        ("нет ИНН", _remove("//r:Organization/r:INN")),
        ("ИНН 9 цифр", _set("//r:Organization/r:INN", "770708389")),
        ("ИНН с буквами", _set("//r:Organization/r:INN", "77070838ab")),
        ("КПП 8 цифр", _set("//r:Organization/r:KPP", "77070100")),
        ("неизвестная фаза", _set("//r:Phase", "during")),
        ("время без пояса", _set("//r:PerformedAt", "2026-10-14T08:20:00")),
        ("температура 2 знака", _set("//r:Temperature", "36.65")),
        ("температура вне диапазона", _set("//r:Temperature", "50.0")),
        ("пульс не число", _set("//r:Pulse", "быстро")),
        ("АД вне диапазона", _set("//r:Systolic", "20")),
        ("алкоголь отрицательный", _set("//r:Alcohol", "-0.1")),
        ("неизвестный результат", _set("//r:Result", "ok")),
        ("пустые жалобы", _set("//r:Complaints", "")),
        ("нет специалиста", _remove("//r:Specialist")),
        ("пол вне M/F", _set("//r:Gender", "X")),
        ("дата рождения мусор", _set("//r:BirthDate", "21.07.1974")),
        ("нет результата", _remove("//r:Result")),
    ],
)
def test_record_violations_are_rejected(
    name: str, mutation: Callable[[etree._Element], None]
) -> None:
    """Каждое нарушение формата ловится схемой."""
    data = build_record_xml(JournalKind.MEDICAL, samples.medical())
    assert validate_xml(_mutate(data, mutation), "record"), name


def test_structural_violations_are_rejected() -> None:
    """Неверная версия, id, порядок элементов, лишние элементы и чужой namespace."""
    data = build_record_xml(JournalKind.MEDICAL, samples.medical())
    assert validate_xml(_mutate(data, lambda r: r.set("version", "2.0")), "record")
    assert validate_xml(_mutate(data, lambda r: r.set("id", "not-a-uuid")), "record")
    assert validate_xml(_mutate(data, lambda r: r.set("id", str(uuid.uuid4()).upper())), "record")

    def extra(root: etree._Element) -> None:
        """Добавляет неизвестный элемент."""
        etree.SubElement(root, f"{{{NS_RECORD}}}Unexpected").text = "x"

    def swap(root: etree._Element) -> None:
        """Меняет порядок Source и Organization."""
        src, org = root[0], root[1]
        root.remove(src)
        org.addnext(src)

    def both(root: etree._Element) -> None:
        """Добавляет TechnicalInspection к MedicalExamination."""
        etree.SubElement(root, f"{{{NS_RECORD}}}TechnicalInspection")

    for bad in (extra, swap, both):
        assert validate_xml(_mutate(data, bad), "record"), bad.__doc__
    foreign = data.replace(NS_RECORD.encode(), b"urn:other:ns")
    assert validate_xml(foreign, "record")
    assert validate_xml(b"<not xml", "record")


def test_builder_refuses_invalid_data() -> None:
    """Некорректные данные записи не доходят до подписи: билдер бросает XmlInvalidError."""
    bad_snapshot = {
        **samples.SNAPSHOT,
        "organization": {**samples.SNAPSHOT["organization"], "inn": "123"},
    }
    with pytest.raises(XmlInvalidError) as exc:
        build_record_xml(JournalKind.MEDICAL, samples.medical(snapshot=bad_snapshot))
    assert exc.value.code == "record_xml_invalid"
    with pytest.raises(XmlInvalidError):
        build_record_xml(JournalKind.MEDICAL, samples.medical(complaints="  "))
    naive = datetime(2026, 10, 14, 8, 20)
    with pytest.raises(XmlInvalidError):
        build_record_xml(JournalKind.MEDICAL, samples.medical(performed_at=naive))


def test_xxe_and_doctype_are_rejected() -> None:
    """DOCTYPE и внешние сущности запрещены (защита от XXE)."""
    evil = (
        b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]>'
        b'<ElectronicRecord xmlns="urn:predreis:journals:record:1.0" version="1.0">&e;</ElectronicRecord>'
    )
    errors = validate_xml(evil, "record")
    assert errors and "DOCTYPE" in errors[0]
    bomb = b'<?xml version="1.0"?><!doctype lolz [<!ENTITY a "aaaa">]><r>&a;</r>'
    assert "DOCTYPE" in validate_xml(bomb, "record")[0]


# ---------- journal.xml ----------


def _ref(n: int = 1) -> JournalRecordRef:
    """Минимальная запись журнала."""
    rid = uuid.UUID(int=n)
    return JournalRecordRef(
        record_id=rid,
        source=RecordSource.MANUAL,
        performed_at=datetime(2026, 10, n, 8, 0, tzinfo=samples.MSK),
        result=samples.InspectionResult.ADMITTED,
        xml=FileRef(f"records/{rid}/record.xml", samples.SHA_A),
    )


def _journal(records: list[JournalRecordRef]) -> bytes:
    """Собирает journal.xml с типовыми реквизитами."""
    return build_journal_xml(
        journal_id=uuid.UUID(int=99),
        kind=JournalKind.TECHNICAL,
        issuer=Party("5027236147", "ООО «ПРЕДРЕЙС»"),
        organization=Party("7707083893", "ООО «Тест»"),
        period_from=samples.date(2026, 10, 1),
        period_to=samples.date(2026, 10, 31),
        created_at=datetime(2026, 11, 1, tzinfo=samples.MSK),
        audit=AuditRef("audit/audit-log.json", samples.SHA_B, 0, samples.SHA_C),
        records=records,
    )


def test_journal_orders_records_by_time_and_counts() -> None:
    """Записи в журнале упорядочены по времени осмотра; count совпадает с числом записей."""
    data = _journal([_ref(5), _ref(2), _ref(9)])
    root = etree.fromstring(data)
    ns = {"j": "urn:predreis:journals:journal:1.0"}
    assert root.xpath("//j:Records/@count", namespaces=ns) == ["3"]
    times = root.xpath("//j:Record/@performedAt", namespaces=ns)
    assert times == sorted(times)


def test_journal_requires_at_least_one_record() -> None:
    """Пустой журнал не проходит проверку."""
    with pytest.raises(XmlInvalidError):
        _journal([])


@pytest.mark.parametrize("sha", ["A" * 64, "a" * 63, "g" * 64, ""])
def test_sha256_format_enforced(sha: str) -> None:
    """SHA-256 — ровно 64 строчных hex-символа."""
    rec = _ref()
    broken = JournalRecordRef(
        record_id=rec.record_id,
        source=rec.source,
        performed_at=rec.performed_at,
        result=rec.result,
        xml=FileRef(rec.xml.path, sha),
    )
    with pytest.raises(XmlInvalidError):
        _journal([broken])


# ---------- manifest.xml и пути ----------


@pytest.mark.parametrize(
    "path",
    ["../etc/passwd", "/abs/path", "a/../b", "a//b", "a\\b", "./a", "", "a/", "records/./x"],
)
def test_unsafe_archive_paths_rejected(path: str) -> None:
    """Пути с «..», абсолютные, с обратным слешем и пустыми сегментами запрещены."""
    with pytest.raises(ValidationFailedError) as exc:
        safe_archive_path(path)
    assert exc.value.code == "unsafe_path"


def test_manifest_rejects_unknown_role_and_unsafe_path() -> None:
    """Манифест не принимает неизвестные роли файлов и небезопасные пути."""
    ok = ManifestFile("README.txt", "readme", 1, samples.SHA_A)
    kwargs = {
        "container_id": uuid.UUID(int=1),
        "created_at": datetime(2026, 11, 1, tzinfo=samples.MSK),
        "generator": "t",
    }
    assert build_manifest_xml(files=[ok], **kwargs)
    with pytest.raises(XmlInvalidError):
        build_manifest_xml(files=[ManifestFile("a.txt", "weird", 1, samples.SHA_A)], **kwargs)
    with pytest.raises(ValidationFailedError):
        build_manifest_xml(files=[ManifestFile("../a.txt", "readme", 1, samples.SHA_A)], **kwargs)
    with pytest.raises(ValidationFailedError):
        build_manifest_xml(
            files=[ManifestFile("a.txt", "record-signature", 1, samples.SHA_A, signed_file="/x")],
            **kwargs,
        )
