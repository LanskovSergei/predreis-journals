"""Снимок реквизитов на момент осмотра: подписанная запись не меняется задним числом."""

from __future__ import annotations

from typing import Any

from app.models.catalog import Driver, Organization, User, Vehicle


def build_snapshot(
    *,
    organization: Organization,
    specialist: User,
    driver: Driver | None = None,
    vehicle: Vehicle | None = None,
) -> dict[str, Any]:
    """Собирает JSON-снимок реквизитов организации, водителя, ТС и специалиста."""
    snap: dict[str, Any] = {
        "organization": {
            "inn": organization.inn,
            "name": organization.name,
            "short_name": organization.short_name,
            "legal_address": organization.legal_address,
        },
        "specialist": {"full_name": specialist.full_name},
    }
    if driver is not None:
        snap["driver"] = {
            "full_name": driver.full_name,
            "birth_date": driver.birth_date.isoformat(),
            "gender": driver.gender.value,
        }
    if vehicle is not None:
        snap["vehicle"] = {
            "brand": vehicle.brand,
            "model": vehicle.model,
            "vehicle_type": vehicle.vehicle_type,
            "plate": vehicle.plate,
        }
    return snap
