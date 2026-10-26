"""Описания отчётных документов (колонки, шапки, реквизиты сторон) для движка PDF."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from app.core.config import Settings
from app.domain.masking import MEDICAL_PRIVACY_NOTICE
from app.modules.reports.pdf import HeaderCell, RegistrySpec

MEDICAL_WIDTHS: list[float] = [3, 7.5, 5, 10.5, 7.5, 4, 5, 5, 4, 5.5, 5.5, 8, 7.5, 22]
MEDICAL_ALIGNS = ["c", "c", "c", "l", "c", "c", "c", "c", "c", "c", "c", "c", "c", "l"]
TECHNICAL_WIDTHS: list[float] = [4, 8, 7, 15, 11, 8, 10, 15, 22]
TECHNICAL_ALIGNS = ["c", "c", "c", "l", "c", "c", "c", "l", "l"]

MEDICAL_HEADER = [
    HeaderCell("№", 0, 0, rowspan=2),
    HeaderCell("Дата проведения медицинского осмотра", 1, 0, rowspan=2),
    HeaderCell("Время проведения медицинского осмотра", 2, 0, rowspan=2),
    HeaderCell("Ф.И.О. водителя", 3, 0, rowspan=2),
    HeaderCell("Дата рождения", 4, 0, rowspan=2),
    HeaderCell("Пол водителя", 5, 0, rowspan=2),
    HeaderCell(
        "Результаты исследований, указанные в п. 12 Порядка проведения предсменных, "
        "послесменных медицинских осмотров",
        6,
        0,
        colspan=6,
    ),
    HeaderCell(
        "Заключение о результатах медицинских осмотров в соответствии с п. 18 Порядка "
        "проведения предсменных, послесменных медицинских осмотров",
        12,
        0,
        rowspan=2,
    ),
    HeaderCell(
        "Электронная подпись медицинского работника (№ сертификата, владелец ЭЦП, срок действия)",
        13,
        0,
        rowspan=2,
    ),
    HeaderCell("жалобы, анамнез", 6, 1),
    HeaderCell("АД (мм рт.ст.)", 7, 1),
    HeaderCell("PS (уд/мин)", 8, 1),
    HeaderCell("Температура тела", 9, 1),
    HeaderCell("Проба на алкоголь в выдыхаемом воздухе (mg/L)", 10, 1),
    HeaderCell(
        "Наличие/отсутствие признаков воздействия вредных и (или) опасных производственных "
        "факторов, состояний и заболеваний, препятствующих выполнению трудовых обязанностей",
        11,
        1,
    ),
]

TECHNICAL_HEADER = [
    HeaderCell(t, i, 0)
    for i, t in enumerate(
        [
            "№",
            "Дата проведения техконтроля",
            "Время проведения техконтроля",
            "Марка и модель транспортного средства",
            "Госномер транспортного средства",
            "Показания одометра",
            "Отметка о прохождении контроля",
            "ФИО контролёра",
            "Подпись контролёра (номер сертификата, ФИО, срок действия)",
        ]
    )
]


def _signature(sig: Mapping[str, str] | None) -> str:
    """Текст ячейки подписи: сертификат, владелец и срок действия."""
    if not sig:
        return ""
    return "\n".join(
        [sig["serial"], sig["owner"], f"Действителен с {sig['valid_from']} по {sig['valid_to']}"]
    )


def medical_cells(row: Mapping[str, Any]) -> list[str]:
    """Ячейки строки журнала медосмотров (медицинские показатели уже скрыты)."""
    return [
        str(row["n"]),
        row["date"],
        row["time"],
        row["driver_name"],
        row["birth_date"],
        row["gender"],
        str(row["complaints"]),
        str(row["blood_pressure"]),
        str(row["pulse"]),
        str(row["temperature"]),
        str(row["alcohol_mgl"]),
        str(row["harmful_factors"]),
        row["conclusion"],
        _signature(row["signature"]),
    ]


def technical_cells(row: Mapping[str, Any]) -> list[str]:
    """Ячейки строки журнала техконтроля."""
    return [
        str(row["n"]),
        row["date"],
        row["time"],
        row["vehicle_name"],
        row["plate"],
        str(row["odometer"]),
        row["conclusion"],
        row["specialist_name"],
        _signature(row["signature"]),
    ]


def _parties(
    customer: Mapping[str, Any], settings: Settings, *, with_license: bool
) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """Реквизиты заказчика и исполнителя."""
    left = [
        ("Заказчик:", str(customer["name"])),
        ("ИНН:", str(customer["inn"])),
        ("Адрес:", str(customer.get("address") or "—")),
    ]
    right = [
        ("Исполнитель:", settings.executor_name),
        ("ИНН:", settings.executor_inn),
        ("Адрес:", settings.executor_address),
    ]
    if with_license:
        right.append(("Лицензия", settings.executor_license))
    right += [("Тел:", settings.executor_phone), ("Email:", settings.executor_email)]
    return left, right


def build_spec(
    *,
    medical: bool,
    title: str,
    rows: Sequence[Mapping[str, Any]],
    customer: Mapping[str, Any],
    settings: Settings,
    period: tuple[str, str] | None = None,
    stamp: Mapping[str, str] | None = None,
) -> RegistrySpec:
    """Собирает описание документа для журнала медосмотров или техконтроля."""
    left, right = _parties(customer, settings, with_license=medical)
    full_title = f"{title} в период с {period[0]} по {period[1]}" if period else title
    stamp_lines = (
        [
            f"Файл подписан электронной цифровой подписью {settings.executor_name}",
            f"Сертификат: {stamp['serial']}",
            f"Владелец: {stamp['subject']}",
            f"Действителен с {stamp['valid_from']} по {stamp['valid_to']}",
        ]
        if stamp
        else None
    )
    if medical:
        return RegistrySpec(
            title=full_title,
            left=left,
            right=right,
            header=MEDICAL_HEADER,
            widths_pct=MEDICAL_WIDTHS,
            aligns=MEDICAL_ALIGNS,
            rows=[medical_cells(r) for r in rows],
            notice=MEDICAL_PRIVACY_NOTICE,
            stamp=stamp_lines,
            header_rows=2,
        )
    return RegistrySpec(
        title=full_title,
        left=left,
        right=right,
        header=TECHNICAL_HEADER,
        widths_pct=TECHNICAL_WIDTHS,
        aligns=TECHNICAL_ALIGNS,
        rows=[technical_cells(r) for r in rows],
        stamp=stamp_lines,
        header_rows=1,
    )
