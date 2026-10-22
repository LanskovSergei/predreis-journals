"""Модели SQLAlchemy. Импорт всех модулей нужен для Alembic autogenerate."""

from app.models.audit import AuditLog
from app.models.base import Base
from app.models.catalog import Driver, Organization, User, Vehicle
from app.models.documents import DeletionRequest, EJournal, EJournalItem, RecordDocument
from app.models.integration import InboxEvent, OutboxEvent, SyncState
from app.models.ocr import OcrBatch, OcrItem
from app.models.records import MedicalRecord, TechnicalRecord

__all__ = [
    "AuditLog",
    "Base",
    "DeletionRequest",
    "Driver",
    "EJournal",
    "EJournalItem",
    "InboxEvent",
    "MedicalRecord",
    "OcrBatch",
    "OcrItem",
    "Organization",
    "OutboxEvent",
    "RecordDocument",
    "SyncState",
    "TechnicalRecord",
    "User",
    "Vehicle",
]
