"""Данные подставного Предрейса: организации, водители, ТС, пользователи (детерминированные id)."""

from __future__ import annotations

import uuid
from typing import Any

NS = uuid.UUID("12345678-1234-5678-1234-567812345678")


def uid(name: str) -> str:
    """Стабильный UUID по имени."""
    return str(uuid.uuid5(NS, name))


STAMP = "2026-06-04T06:29:56.962981Z"

ORG_LLC = uid("org-llc")
ORG_IP = uid("org-ip")

ORGANIZATIONS: list[dict[str, Any]] = [
    {
        "id": ORG_LLC,
        "inn": "7700000001",
        "kpp": "770001001",
        "ogrn": "1027700000001",
        "name_short": "ООО Тест Транс",
        "name_full": "Общество с ограниченной ответственностью Тест Транс",
        "legal_address": "г. Москва, ул. Тестовая, д. 1",
        "is_active": True,
        "epl_ready": True,
        "created_at": STAMP,
        "updated_at": STAMP,
    },
    {
        "id": ORG_IP,
        "inn": "770000000000",
        "kpp": None,
        "ogrn": "300000000000000",
        "name_short": "ИП ИВАНОВ ИВАН ИВАНОВИЧ",
        "name_full": "Индивидуальный предприниматель Иванов Иван Иванович",
        "legal_address": None,
        "is_active": True,
        "epl_ready": False,
        "created_at": STAMP,
        "updated_at": STAMP,
    },
]


def _driver(
    key: str,
    org: str,
    last: str,
    first: str,
    middle: str,
    gender: str | None,
    born: str,
    series: str | None,
    number: str,
) -> dict[str, Any]:
    """Строка справочника водителей."""
    return {
        "id": uid(key),
        "org_id": org,
        "gender": gender,
        "last_name": last,
        "first_name": first,
        "middle_name": middle,
        "birth_date": f"{born}T00:00:00",
        "license_series": series,
        "license_number": number,
        "is_active": True,
        "created_at": STAMP,
        "updated_at": STAMP,
    }


DRIVERS = [
    _driver(
        "drv-1",
        ORG_LLC,
        "Водителев",
        "Василий",
        "Васильевич",
        None,
        "1985-05-20",
        "7700",
        "123456",
    ),
    _driver(
        "drv-2", ORG_LLC, "Шофёров", "Сергей", "Петрович", "M", "1979-02-11", "9910", "915125"
    ),
    _driver(
        "drv-3", ORG_LLC, "Рулева", "Ольга", "Ивановна", None, "1990-09-30", None, "9911 777888"
    ),
    _driver("drv-4", ORG_IP, "Петров", "Пётр", "Петрович", None, "2000-09-09", None, "9900000000"),
]


def _vehicle(
    key: str, org: str, plate: str, brand: str, model: str, kind: str, cat: str
) -> dict[str, Any]:
    """Строка справочника ТС."""
    return {
        "id": uid(key),
        "org_id": org,
        "plate_number": plate,
        "brand": brand,
        "model": model,
        "type": kind,
        "category": cat,
        "is_active": True,
        "created_at": STAMP,
        "updated_at": STAMP,
    }


VEHICLES = [
    _vehicle("veh-1", ORG_LLC, "А123ВС77", "КАМАЗ", "65115", "грузовой", "C"),
    _vehicle("veh-2", ORG_LLC, "О224ЕК790", "ГАЗон", "Next", "грузовой", "C"),
    _vehicle("veh-3", ORG_IP, "О231ТА790", "VOLKSWAGEN", "TOURAN", "легковой", "B"),
]

PASSWORD = "password"


def _user(
    role: str,
    last: str,
    first: str,
    middle: str,
    *,
    org: str | None = None,
    access: bool = True,
    cert: bool = True,
    email: str | None = None,
) -> dict[str, Any]:
    """Пользователь ПРЕДРЕЙСа."""
    return {
        "id": uid(f"user-{role}-{last}"),
        "email": email or f"{role}@example.ru",
        "last_name": last,
        "first_name": first,
        "middle_name": middle,
        "role": role,
        "org_id": org,
        "journals_access": access,
        "is_active": True,
        "has_cert": cert,
    }


USERS = {
    "superadmin": _user("superadmin", "Главный", "Админ", "Суперович"),
    "predreis": _user(
        "predreise", "Менеджерова", "Мария", "Петровна", email="predreis@example.ru"
    ),
    "medic": _user("medic", "Сидорова", "Анна", "Сергеевна"),
    "mechanic": _user("mechanic", "Механиков", "Дмитрий", "Юрьевич"),
    "client": _user("client", "Клиентов", "Клим", "Климович", org=ORG_LLC),
    "noaccess": _user(
        "predreise", "Безправов", "Борис", "Борисович", access=False, email="noaccess@example.ru"
    ),
    "nocert": _user(
        "medic", "Безсертов", "Сергей", "Сергеевич", cert=False, email="nocert@example.ru"
    ),
}
