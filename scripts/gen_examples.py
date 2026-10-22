"""Генерирует образцы XML в docs/examples (они же проверяются тестами по XSD)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tests.xml_samples import all_examples  # noqa: E402


def main() -> None:
    """Пишет образцы в docs/examples."""
    target = ROOT / "docs" / "examples"
    target.mkdir(parents=True, exist_ok=True)
    for name, data in all_examples().items():
        (target / name).write_bytes(data)
        print(f"записан {target / name}")


if __name__ == "__main__":
    main()
