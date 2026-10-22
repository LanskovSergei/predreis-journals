"""XSD-схемы электронных документов и безопасная валидация XML."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from lxml import etree

from app.core.errors import AppError

SCHEMA_DIR = Path(__file__).resolve().parent
SchemaName = Literal["record", "journal", "manifest"]

NS_RECORD = "urn:predreis:journals:record:1.0"
NS_JOURNAL = "urn:predreis:journals:journal:1.0"
NS_MANIFEST = "urn:predreis:journals:manifest:1.0"
FORMAT_VERSION = "1.0"

# Без разрешения сущностей, DTD и сети: защита от XXE и «миллиарда смехов».
_PARSER = etree.XMLParser(
    resolve_entities=False, no_network=True, load_dtd=False, dtd_validation=False, huge_tree=False
)


class XmlInvalidError(AppError):
    """XML не соответствует схеме (ошибка данных или баг генерации)."""

    status_code = 422
    code = "xml_invalid"


@lru_cache
def _schema(name: SchemaName) -> etree.XMLSchema:
    """Загружает и кэширует XSD."""
    return etree.XMLSchema(etree.parse(str(SCHEMA_DIR / f"{name}.xsd")))


def validate_xml(data: bytes, name: SchemaName) -> list[str]:
    """Проверяет XML по схеме; возвращает список ошибок (пустой — документ корректен)."""
    if b"<!DOCTYPE" in data[:2048].upper() or b"<!ENTITY" in data.upper():
        return ["DOCTYPE и объявления сущностей запрещены"]
    try:
        doc = etree.fromstring(data, parser=_PARSER)
    except etree.XMLSyntaxError as exc:
        return [f"Некорректный XML: {exc}"]
    schema = _schema(name)
    if schema.validate(doc):
        return []
    return [f"строка {e.line}: {e.message}" for e in schema.error_log]


def ensure_valid(data: bytes, name: SchemaName, *, code: str | None = None) -> None:
    """Бросает XmlInvalidError, если XML не соответствует схеме."""
    errors = validate_xml(data, name)
    if errors:
        raise XmlInvalidError(
            f"XML ({name}) не соответствует схеме: {errors[0]}", code=code, details=errors[:20]
        )
