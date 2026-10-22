"""Перечисления предметной области."""

from __future__ import annotations

from enum import Enum


class Role(str, Enum):
    """Роли пользователей платформы (значения согласовать с Предрейсом)."""

    CLIENT = "client"
    DISPATCHER = "dispatcher"
    MEDIC = "medic"
    MECHANIC = "mechanic"
    PREDREIS = "predreis"
    ADMIN = "admin"
    SA = "superadmin"


class JournalKind(str, Enum):
    """Вид журнала."""

    MEDICAL = "medical"
    TECHNICAL = "technical"


class RecordStatus(str, Enum):
    """Статус записи архива: А — unsigned, Б — signed, В — in_journal (ТЗ, стр. 6)."""

    UNSIGNED = "unsigned"
    SIGNED = "signed"
    IN_JOURNAL = "in_journal"


class RecordSource(str, Enum):
    """Источник записи."""

    MANUAL = "manual"
    OCR = "ocr"
    EPL = "epl"


class WaybillKind(str, Enum):
    """Вид путевого листа (производный от источника записи)."""

    PAPER = "paper"
    EPL = "epl"


class InspectionPhase(str, Enum):
    """Тип медосмотра."""

    PRE = "pre"
    POST = "post"


class InspectionResult(str, Enum):
    """Результат осмотра / контроля."""

    ADMITTED = "admitted"
    NOT_ADMITTED = "not_admitted"


class HarmfulFactors(str, Enum):
    """Признаки воздействия вредных факторов."""

    ABSENT = "absent"
    DETECTED = "detected"


class Gender(str, Enum):
    """Пол водителя."""

    MALE = "M"
    FEMALE = "F"


class ContractType(str, Enum):
    """Тип договора организации."""

    MED = "med"
    TECH = "tech"
    MEDTECH = "medtech"


class WorkFormat(str, Enum):
    """Формат работы организации."""

    EPL = "epl"
    PAPER = "paper"
    HYBRID = "hybrid"


class EJournalStatus(str, Enum):
    """Статус электронного журнала (ZIP-контейнера)."""

    DRAFT = "draft"
    AWAITING_SIGNATURE = "awaiting_signature"
    SIGNED = "signed"
    REJECTED = "rejected"


class DeletionStatus(str, Enum):
    """Статус запроса на удаление подписанной записи."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class OcrStampType(str, Enum):
    """Тип штампа на бумажном путевом листе."""

    PRE_MEDICAL = "pre_medical"
    POST_MEDICAL = "post_medical"
    TECHNICAL = "technical"


class OcrBatchStatus(str, Enum):
    """Статус пакета распознавания."""

    UPLOADED = "uploaded"
    PROCESSING = "processing"
    READY = "ready"
    COMMITTED = "committed"
    FAILED = "failed"


class SignatureKind(str, Enum):
    """Чьей подписью подписывается документ."""

    PERSONAL = "personal"
    ORGANIZATION = "organization"
