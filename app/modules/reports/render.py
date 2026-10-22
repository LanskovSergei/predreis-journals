"""Рендеринг отчётных PDF: Jinja2 (HTML) → WeasyPrint (PDF)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "templates" / "pdf"

_env = Environment(
    loader=FileSystemLoader(TEMPLATES_DIR),
    autoescape=select_autoescape(["html"]),
    trim_blocks=True,
    lstrip_blocks=True,
)


def render_html(template: str, **context: Any) -> str:
    """Рендерит HTML-шаблон отчёта."""
    return _env.get_template(template).render(**context)


def _write_pdf(html: str) -> bytes:
    """Синхронно конвертирует HTML в PDF (WeasyPrint импортируется лениво)."""
    from weasyprint import HTML

    return HTML(string=html).write_pdf()


async def html_to_pdf(html: str) -> bytes:
    """Конвертирует HTML в PDF в отдельном потоке, не блокируя event loop."""
    return await asyncio.to_thread(_write_pdf, html)
