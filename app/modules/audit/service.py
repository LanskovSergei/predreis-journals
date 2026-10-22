"""Журнал аудита с хеш-цепочкой: каждая запись хранит хеш предыдущей."""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import ARRAY, String, any_, bindparam, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import Principal
from app.models.audit import AuditLog

logger = logging.getLogger(__name__)

GENESIS_HASH = "0" * 64
AUDIT_LOCK_KEY = 7_340_001


def compute_hash(prev_hash: str, body: dict[str, Any]) -> str:
    """Считает SHA-256 от предыдущего хеша и канонического JSON тела записи."""
    canonical = json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256((prev_hash + canonical).encode("utf-8")).hexdigest()


def _body(row: AuditLog) -> dict[str, Any]:
    """Формирует хешируемое тело записи аудита."""
    return {
        "ts": row.ts.isoformat(),
        "actor_id": row.actor_id,
        "actor_role": row.actor_role,
        "ip": row.ip,
        "session_id": row.session_id,
        "action": row.action,
        "entity_type": row.entity_type,
        "entity_id": row.entity_id,
        "payload": row.payload,
    }


async def append_audit(
    session: AsyncSession,
    actor: Principal | None,
    *,
    action: str,
    entity_type: str,
    entity_id: str | None = None,
    payload: dict[str, Any] | None = None,
) -> AuditLog:
    """Добавляет запись аудита. actor=None означает системное действие."""
    await session.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": AUDIT_LOCK_KEY})
    prev = (
        await session.execute(select(AuditLog.hash).order_by(AuditLog.id.desc()).limit(1))
    ).scalar_one_or_none()
    row = AuditLog(
        ts=datetime.now(timezone.utc),
        actor_id=str(actor.user_id) if actor else None,
        actor_role=actor.role.value if actor else "system",
        ip=actor.ip if actor else None,
        session_id=actor.session_id if actor else None,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        payload=payload or {},
        prev_hash=prev or GENESIS_HASH,
        hash="",
    )
    row.hash = compute_hash(row.prev_hash, _body(row))
    session.add(row)
    await session.flush()
    return row


async def verify_chain(session: AsyncSession) -> bool:
    """Проверяет целостность всей хеш-цепочки аудита."""
    rows = (await session.execute(select(AuditLog).order_by(AuditLog.id))).scalars()
    prev = GENESIS_HASH
    for row in rows:
        if row.prev_hash != prev or row.hash != compute_hash(prev, _body(row)):
            logger.error("Нарушена цепочка аудита на записи id=%s", row.id)
            return False
        prev = row.hash
    return True


@dataclass(frozen=True, slots=True)
class AuditExport:
    """Выгрузка журнала аудита: файл, число записей и голова глобальной цепочки."""

    data: bytes
    entries: int
    chain_head: str


async def export_audit_json(session: AsyncSession, entity_ids: list[str]) -> AuditExport:
    """Выгружает записи аудита по указанным сущностям (JSON с каждым prev_hash и hash)."""
    rows: list[AuditLog] = []
    if entity_ids:
        ids = bindparam("ids", entity_ids, type_=ARRAY(String))
        rows = list(
            (
                await session.execute(
                    select(AuditLog).where(AuditLog.entity_id == any_(ids)).order_by(AuditLog.id)
                )
            )
            .scalars()
            .all()
        )
    head = (
        await session.execute(select(AuditLog.hash).order_by(AuditLog.id.desc()).limit(1))
    ).scalar_one_or_none() or GENESIS_HASH
    entries = [{**_body(r), "id": r.id, "prev_hash": r.prev_hash, "hash": r.hash} for r in rows]
    doc = {"format": "1.0", "genesis_hash": GENESIS_HASH, "chain_head": head, "entries": entries}
    data = json.dumps(doc, ensure_ascii=False, sort_keys=True, indent=1).encode("utf-8")
    return AuditExport(data=data, entries=len(entries), chain_head=head)


def verify_audit_export(data: bytes) -> list[str]:
    """Пересчитывает хеш каждой записи выгрузки; возвращает список расхождений."""
    try:
        doc = json.loads(data)
        entries = doc["entries"]
    except (ValueError, KeyError, TypeError):
        return ["Некорректный формат выгрузки аудита"]
    errors: list[str] = []
    body_keys = (
        "ts",
        "actor_id",
        "actor_role",
        "ip",
        "session_id",
        "action",
        "entity_type",
        "entity_id",
        "payload",
    )
    for e in entries:
        body = {k: e.get(k) for k in body_keys}
        if compute_hash(e.get("prev_hash", ""), body) != e.get("hash"):
            errors.append(f"Хеш записи аудита id={e.get('id')} не совпадает")
    return errors
