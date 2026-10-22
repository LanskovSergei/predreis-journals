"""Выгружает схему OpenAPI в docs/openapi.json — контракт для разработчика фронтенда."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.main import create_app


def main() -> None:
    """Пишет openapi.json рядом с документацией."""
    target = Path(__file__).resolve().parents[1] / "docs" / "openapi.json"
    schema = create_app().openapi()
    target.write_text(json.dumps(schema, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"OpenAPI записан: {target}")


if __name__ == "__main__":
    main()
