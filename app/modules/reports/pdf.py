"""Быстрая постраничная отрисовка реестров в PDF (ReportLab, канвас без Platypus).

Раскладка считается заранее (высоты строк, разбиение на страницы), затем страницы рисуются потоком.
Это на порядок быстрее и экономнее по памяти, чем HTML→PDF: память почти не растёт с объёмом.
Шрифт DejaVu лежит в репозитории (`app/assets/fonts`), системных шрифтов и библиотек не требуется.
"""

from __future__ import annotations

import asyncio
import io
from collections.abc import Sequence
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.lib.utils import simpleSplit
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas

FONTS_DIR = Path(__file__).resolve().parents[2] / "assets" / "fonts"
FONT, FONT_BOLD = "DejaVuSans", "DejaVuSans-Bold"
PAGE_W, PAGE_H = landscape(A4)
MARGIN_X, MARGIN_TOP, MARGIN_BOTTOM = 10 * mm, 12 * mm, 16 * mm
BODY_PT, HEAD_PT, TITLE_PT, PARTY_PT = 7.5, 6.0, 10.0, 8.0
PAD = 2.0
GREY = colors.HexColor("#f0f0f0")
BLUE = colors.HexColor("#1f4e9c")
BLUE_FILL = colors.HexColor("#eaf1fb")


@lru_cache
def register_fonts() -> None:
    """Регистрирует встроенные шрифты один раз."""
    pdfmetrics.registerFont(TTFont(FONT, str(FONTS_DIR / "DejaVuSans.ttf")))
    pdfmetrics.registerFont(TTFont(FONT_BOLD, str(FONTS_DIR / "DejaVuSans-Bold.ttf")))


@dataclass(frozen=True, slots=True)
class HeaderCell:
    """Ячейка шапки таблицы: позиция в сетке и объединения."""

    text: str
    col: int
    row: int
    colspan: int = 1
    rowspan: int = 1


@dataclass(slots=True)
class RegistrySpec:
    """Документ: реквизиты сторон, шапка и строки таблицы, примечание и плашка подписи."""

    title: str
    left: list[tuple[str, str]]
    right: list[tuple[str, str]]
    header: list[HeaderCell]
    widths_pct: list[float]
    aligns: list[str]  # "c" — по центру, "l" — по левому краю
    rows: Sequence[Sequence[str]]
    notice: str | None = None
    stamp: list[str] | None = None
    header_rows: int = 2
    extra: dict[str, str] = field(default_factory=dict)


def _fit(line: str, font: str, size: float, width: float) -> list[str]:
    """Режет строку по символам, если даже одно слово не помещается в ширину ячейки."""
    if stringWidth(line, font, size) <= width:
        return [line]
    out: list[str] = []
    current = ""
    for ch in line:
        if current and stringWidth(current + ch, font, size) > width:
            out.append(current)
            current = ch
        else:
            current += ch
    out.append(current)
    return out


def _wrap(text: str, font: str, size: float, width: float) -> list[str]:
    """Переносит текст по словам в заданную ширину; явные переводы строк сохраняются."""
    lines: list[str] = []
    for part in text.split("\n"):
        if stringWidth(part, font, size) <= width:
            lines.append(part)
            continue
        for chunk in simpleSplit(part, font, size, width) or [""]:
            lines.extend(_fit(chunk, font, size, width))
    return lines


def _lines_height(count: int, size: float) -> float:
    """Высота блока из count строк."""
    return count * size * 1.22


def _party_block(pairs: list[tuple[str, str]], width: float) -> list[tuple[str, list[str]]]:
    """Реквизиты стороны: подпись (жирным) и перенесённое значение."""
    out = []
    for label, value in pairs:
        offset = stringWidth(label + " ", FONT_BOLD, PARTY_PT)
        out.append((label, _wrap(value, FONT, PARTY_PT, width - offset)))
    return out


@dataclass(slots=True)
class _Layout:
    """Результат раскладки: размеры колонок и шапки, высоты строк, разбиение на страницы."""

    xs: list[float]
    head_heights: list[float]
    row_heights: list[float]
    cell_lines: list[list[list[str]]]
    pages: list[tuple[int, int]]
    first_top: float
    tail_page: bool
    total_pages: int


def _layout(spec: RegistrySpec) -> _Layout:
    """Считает раскладку документа."""
    usable = PAGE_W - 2 * MARGIN_X
    widths = [usable * p / sum(spec.widths_pct) for p in spec.widths_pct]
    xs = [MARGIN_X]
    for w in widths:
        xs.append(xs[-1] + w)

    # шапка: высоты строк с учётом объединений
    head = [0.0] * spec.header_rows
    spanned: list[tuple[HeaderCell, float]] = []
    for cell in spec.header:
        width = sum(widths[cell.col : cell.col + cell.colspan]) - 2 * PAD
        need = _lines_height(len(_wrap(cell.text, FONT_BOLD, HEAD_PT, width)), HEAD_PT) + 2 * PAD
        if cell.rowspan == 1:
            head[cell.row] = max(head[cell.row], need)
        else:
            spanned.append((cell, need))
    for cell, need in spanned:
        total = sum(head[cell.row : cell.row + cell.rowspan])
        if total < need:
            head[cell.row + cell.rowspan - 1] += need - total
    head_h = sum(head)

    # строки: переносы и высоты
    cell_lines: list[list[list[str]]] = []
    heights: list[float] = []
    for row in spec.rows:
        lines = [_wrap(str(v), FONT, BODY_PT, widths[i] - 2 * PAD) for i, v in enumerate(row)]
        cell_lines.append(lines)
        heights.append(_lines_height(max(len(x) for x in lines), BODY_PT) + 2 * PAD)

    # верх первой страницы: реквизиты сторон и заголовок
    half = (usable - 12) / 2
    left = _party_block(spec.left, half)
    right = _party_block(spec.right, half)
    parties_h = max(
        sum(_lines_height(len(v), PARTY_PT) for _, v in left),
        sum(_lines_height(len(v), PARTY_PT) for _, v in right),
    )
    title_lines = _wrap(spec.title, FONT_BOLD, TITLE_PT, usable)
    first_top = parties_h + 10 + _lines_height(len(title_lines), TITLE_PT) + 10

    # страницы
    bottom = PAGE_H - MARGIN_TOP - MARGIN_BOTTOM
    pages: list[tuple[int, int]] = []
    start, used, cap = 0, 0.0, bottom - first_top - head_h
    for i, h in enumerate(heights):
        if used + h > cap and i > start:
            pages.append((start, i))
            start, used, cap = i, 0.0, bottom - head_h
        used += h
    pages.append((start, len(heights)))
    left_on_last = cap - used

    # примечание и плашка подписи после таблицы
    tail_h = 0.0
    if spec.notice:
        tail_h += _lines_height(len(_wrap(spec.notice, FONT, 7, usable)), 7) + 8
    if spec.stamp:
        tail_h += _lines_height(len(spec.stamp), 8) + 2 * PAD * 3 + 14
    tail_page = tail_h > left_on_last
    return _Layout(
        xs,
        head,
        heights,
        cell_lines,
        pages,
        first_top,
        tail_page,
        len(pages) + (1 if tail_page else 0),
    )


def _draw_parties(c: Canvas, spec: RegistrySpec, y: float) -> float:
    """Рисует реквизиты заказчика и исполнителя; возвращает координату низа блока."""
    usable = PAGE_W - 2 * MARGIN_X
    half = (usable - 12) / 2
    bottoms = []
    for pairs, x in ((spec.left, MARGIN_X), (spec.right, MARGIN_X + half + 12)):
        cursor = y
        for label, lines in _party_block(pairs, half):
            offset = stringWidth(label + " ", FONT_BOLD, PARTY_PT)
            for n, text in enumerate(lines):
                baseline = cursor - PARTY_PT
                if n == 0:
                    c.setFont(FONT_BOLD, PARTY_PT)
                    c.drawString(x, baseline, label)
                c.setFont(FONT, PARTY_PT)
                c.drawString(x + offset, baseline, text)
                cursor -= _lines_height(1, PARTY_PT)
        bottoms.append(cursor)
    return min(bottoms)


def _draw_title(c: Canvas, spec: RegistrySpec, y: float) -> float:
    """Рисует заголовок по центру."""
    c.setFont(FONT_BOLD, TITLE_PT)
    for line in _wrap(spec.title, FONT_BOLD, TITLE_PT, PAGE_W - 2 * MARGIN_X):
        c.drawCentredString(PAGE_W / 2, y - TITLE_PT, line)
        y -= _lines_height(1, TITLE_PT)
    return y


def _draw_header(c: Canvas, spec: RegistrySpec, lay: _Layout, y: float) -> float:
    """Рисует шапку таблицы; возвращает координату её низа."""
    tops = [y]
    for h in lay.head_heights:
        tops.append(tops[-1] - h)
    c.setLineWidth(0.4)
    for cell in spec.header:
        x0, x1 = lay.xs[cell.col], lay.xs[cell.col + cell.colspan]
        top, bottom = tops[cell.row], tops[cell.row + cell.rowspan]
        c.setFillColor(GREY)
        c.setStrokeColor(colors.black)
        c.rect(x0, bottom, x1 - x0, top - bottom, stroke=1, fill=1)
        c.setFillColor(colors.black)
        c.setFont(FONT_BOLD, HEAD_PT)
        lines = _wrap(cell.text, FONT_BOLD, HEAD_PT, x1 - x0 - 2 * PAD)
        block = _lines_height(len(lines), HEAD_PT)
        baseline = (top + bottom) / 2 + block / 2 - HEAD_PT
        for line in lines:
            c.drawCentredString((x0 + x1) / 2, baseline, line)
            baseline -= _lines_height(1, HEAD_PT)
    return tops[-1]


def _draw_rows(
    c: Canvas, spec: RegistrySpec, lay: _Layout, first: int, last: int, y: float
) -> float:
    """Рисует строки таблицы страницы; возвращает координату низа таблицы."""
    xs = lay.xs
    c.setFont(FONT, BODY_PT)
    c.setLineWidth(0.4)
    c.setStrokeColor(colors.black)
    for i in range(first, last):
        h = lay.row_heights[i]
        c.grid(xs, [y, y - h])
        for col, lines in enumerate(lay.cell_lines[i]):
            centered = spec.aligns[col] == "c"
            baseline = y - PAD - BODY_PT
            for line in lines:
                if centered:
                    c.drawCentredString((xs[col] + xs[col + 1]) / 2, baseline, line)
                else:
                    c.drawString(xs[col] + PAD, baseline, line)
                baseline -= _lines_height(1, BODY_PT)
        y -= h
    return y


def _draw_tail(c: Canvas, spec: RegistrySpec, y: float) -> None:
    """Рисует примечание и плашку подписи."""
    usable = PAGE_W - 2 * MARGIN_X
    if spec.notice:
        c.setFont(FONT, 7)
        y -= 6
        for line in _wrap(spec.notice, FONT, 7, usable):
            c.drawString(MARGIN_X, y - 7, line)
            y -= _lines_height(1, 7)
        y -= 2
    if spec.stamp:
        width = usable * 0.6
        height = _lines_height(len(spec.stamp), 8) + 2 * PAD * 3
        top = y - 14
        c.setStrokeColor(BLUE)
        c.setFillColor(BLUE_FILL)
        c.setLineWidth(1)
        c.rect(MARGIN_X, top - height, width, height, stroke=1, fill=1)
        c.setFillColor(BLUE)
        baseline = top - 3 * PAD - 8 + 2
        for n, line in enumerate(spec.stamp):
            c.setFont(FONT_BOLD if n == 0 else FONT, 8)
            c.drawString(MARGIN_X + 4 * PAD, baseline, line)
            baseline -= _lines_height(1, 8)
        c.setFillColor(colors.black)


def render_pdf(spec: RegistrySpec) -> bytes:
    """Формирует PDF документа (синхронно, CPU-bound)."""
    register_fonts()
    lay = _layout(spec)
    buf = io.BytesIO()
    c = Canvas(buf, pagesize=(PAGE_W, PAGE_H), pageCompression=1)
    c.setTitle(spec.title)
    c.setAuthor("ПРЕДРЕЙС")

    def footer(n: int) -> None:
        """Номер страницы «стр. N из M»."""
        c.setFillColor(colors.black)
        c.setFont(FONT, 8)
        c.drawCentredString(PAGE_W / 2, MARGIN_BOTTOM / 2, f"стр. {n} из {lay.total_pages}")

    for n, (first, last) in enumerate(lay.pages, 1):
        y = PAGE_H - MARGIN_TOP
        if n == 1:
            y = _draw_parties(c, spec, y) - 10
            y = _draw_title(c, spec, y) - 10
        y = _draw_header(c, spec, lay, y)
        y = _draw_rows(c, spec, lay, first, last, y)
        if n == len(lay.pages) and not lay.tail_page:
            _draw_tail(c, spec, y)
        footer(n)
        c.showPage()
    if lay.tail_page:
        _draw_tail(c, spec, PAGE_H - MARGIN_TOP)
        footer(lay.total_pages)
        c.showPage()
    c.save()
    return buf.getvalue()


async def render_pdf_async(spec: RegistrySpec) -> bytes:
    """Формирует PDF в отдельном потоке, не блокируя event loop."""
    return await asyncio.to_thread(render_pdf, spec)
