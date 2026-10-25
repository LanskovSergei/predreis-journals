"""Признаки «не настоящей» подписи."""

from __future__ import annotations

# У ранних титулов вместо подписи стоит заглушка; настоящей подписью она не является.
PLACEHOLDER_SIGNATURES = frozenset({"AUTO_SIGNATURE"})


def is_placeholder(value: str | bytes | None) -> bool:
    """True, если вместо подписи передана заглушка (например, AUTO_SIGNATURE)."""
    if value is None:
        return False
    text = value.decode("utf-8", "ignore") if isinstance(value, bytes) else value
    return text.strip().upper() in PLACEHOLDER_SIGNATURES
