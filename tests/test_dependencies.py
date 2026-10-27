"""Зависимости: всё, что импортирует код, объявлено в pyproject (иначе чистая установка не запустится)."""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

import pytest
import tomllib

ROOT = Path(__file__).resolve().parents[1]
# имя модуля → имя пакета, если они различаются
ALIASES = {"yaml": "pyyaml", "jwt": "pyjwt", "dateutil": "python-dateutil"}
LOCAL = {"app", "tests", "tools", "scripts"}


def _norm(requirement: str) -> str:
    """Имя пакета из строки требования (`pkg[extra]>=1`), в нижнем регистре и через дефис."""
    return re.split(r"[<>=\[ ;]", requirement, maxsplit=1)[0].lower().replace("_", "-")


def _imports(folder: str) -> dict[str, Path]:
    """Сторонние модули верхнего уровня, которые импортирует код каталога, и файл-пример."""
    found: dict[str, Path] = {}
    for path in (ROOT / folder).rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                names = [node.module]
            else:
                continue
            for name in names:
                top = name.split(".")[0]
                if top not in sys.stdlib_module_names and top not in LOCAL:
                    found.setdefault(top, path.relative_to(ROOT))
    return found


@pytest.mark.parametrize(
    ("folder", "include_dev"),
    [("app", False), ("tools", True), ("scripts", True), ("tests", True)],
)
def test_all_imports_are_declared(folder: str, include_dev: bool) -> None:
    """Код приложения не должен зависеть от пакетов, которых нет в основных зависимостях."""
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    allowed = {_norm(d) for d in project["dependencies"]}
    if include_dev:
        allowed |= {_norm(d) for d in project["optional-dependencies"]["dev"]}
    missing = {
        f"{top} ({path})"
        for top, path in _imports(folder).items()
        if _norm(ALIASES.get(top, top)) not in allowed
    }
    assert not missing, f"не объявлены в pyproject.toml: {sorted(missing)}"


def test_lock_files_match_pyproject() -> None:
    """Блокировки содержат все прямые зависимости (если упало: `make lock`)."""
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    lock = (ROOT / "requirements.txt").read_text(encoding="utf-8").lower().replace("_", "-")
    dev_lock = (
        (ROOT / "requirements-dev.txt").read_text(encoding="utf-8").lower().replace("_", "-")
    )
    for requirement in project["dependencies"]:
        assert f"\n{_norm(requirement)}==" in "\n" + lock, f"нет в requirements.txt: {requirement}"
    for requirement in project["optional-dependencies"]["dev"]:
        assert f"\n{_norm(requirement)}==" in "\n" + dev_lock, (
            f"нет в requirements-dev.txt: {requirement}"
        )
