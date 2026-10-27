"""Таблица соответствия ТЗ не ссылается на несуществующие тесты (иначе она вводит в заблуждение)."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_every_test_referenced_in_compliance_doc_exists() -> None:
    """Каждая ссылка вида `файл.py::test_имя` в docs/TZ_COMPLIANCE.md указывает на реальный тест."""
    doc = (ROOT / "docs" / "TZ_COMPLIANCE.md").read_text(encoding="utf-8")
    refs = set(re.findall(r"`(test_\w+)\.py::(test_\w+)`", doc))
    assert len(refs) > 30, "в документе должны быть ссылки на тесты"
    existing: dict[str, set[str]] = {}
    for path in (ROOT / "tests").rglob("test_*.py"):
        existing[path.stem] = set(
            re.findall(r"^(?:async )?def (test_\w+)", path.read_text(encoding="utf-8"), re.M)
        )
    missing = sorted(f"{f}.py::{t}" for f, t in refs if t not in existing.get(f, set()))
    assert not missing, f"таблица ссылается на несуществующие тесты: {missing}"


def test_compliance_doc_has_a_summary_that_adds_up() -> None:
    """Итоговая таблица сходится с числом строк требований."""
    doc = (ROOT / "docs" / "TZ_COMPLIANCE.md").read_text(encoding="utf-8")
    total = int(re.search(r"## Итог: (\d+) требований", doc).group(1))  # type: ignore[union-attr]
    summed = sum(int(n) for n in re.findall(r"^\| [✅☑◐❌] [^|]+\| (\d+) \|", doc, re.M))
    rows = len(re.findall(r"^\| [A-I]\d+ \|", doc, re.M))
    assert total == summed == rows, (total, summed, rows)
