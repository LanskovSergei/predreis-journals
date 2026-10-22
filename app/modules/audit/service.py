"""Журнал аудита с хеш-цепочкой: каждая запись хранит хеш предыдущей."""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, text
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
