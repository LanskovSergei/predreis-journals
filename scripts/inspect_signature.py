"""Проверка разбора реальной подписи Предрейса: серийный номер, владелец, срок действия.

Запуск: python scripts/inspect_signature.py путь\\к\\файлу.txt
Файл — содержимое поля `signature_b64` (base64) либо сама подпись (DER/BER/PEM). Данные никуда не
отправляются. Если разбор не удался, утилита печатает структуру подписи (без персональных данных),
по которой можно понять причину.
"""

from __future__ import annotations

import base64
import binascii
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from asn1crypto import cms

from app.integrations.predreis.cms import extract_cert_info


def load(path: Path) -> bytes:
    """Читает файл: base64-текст либо бинарная подпись."""
    raw = path.read_bytes()
    text = b"".join(raw.split())
    try:
        return base64.b64decode(text + b"=" * (-len(text) % 4), validate=True)
    except (binascii.Error, ValueError):
        return raw


def describe(data: bytes) -> None:
    """Печатает структуру подписи: алгоритмы и число сертификатов (без персональных данных)."""
    print(f"Размер: {len(data)} байт, начало: {data[:8].hex(' ')}")
    try:
        signed = cms.ContentInfo.load(data)["content"]
        print("Версия:", signed["version"].native)
        print(
            "Алгоритмы хеширования:", [a["algorithm"].dotted for a in signed["digest_algorithms"]]
        )
        certs = [c.chosen for c in signed["certificates"] if c.name == "certificate"]
        print("Сертификатов в подписи:", len(certs))
        for cert in certs:
            tbs = cert["tbs_certificate"]
            print(
                " алгоритм ключа:",
                tbs["subject_public_key_info"]["algorithm"]["algorithm"].dotted,
                "| алгоритм подписи:",
                cert["signature_algorithm"]["algorithm"].dotted,
            )
        for info in signed["signer_infos"]:
            print("Алгоритм подписи подписанта:", info["signature_algorithm"]["algorithm"].dotted)
    except (ValueError, KeyError, IndexError, TypeError, AttributeError) as exc:
        print("Структуру прочитать не удалось:", type(exc).__name__, exc)


def main() -> int:
    """Точка входа: 0 — сертификат найден, 1 — нет."""
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    data = load(Path(sys.argv[1]))
    info = extract_cert_info(data)
    if info is None:
        print("Сертификат из подписи извлечь не удалось.")
        describe(data)
        return 1
    print("Серийный номер:", info.serial)
    print("Владелец:      ", info.subject)
    print("Действует:      с", info.valid_from.isoformat(), "по", info.valid_to.isoformat())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
