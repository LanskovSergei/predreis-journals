"""Сведения о сертификате из откреплённой подписи CMS/CAdES (в т.ч. с ГОСТ-алгоритмами).

Предрейс возвращает только `signature_b64`; сертификат подписанта лежит внутри подписи.
Разбор выполняется на уровне ASN.1 (asn1crypto) и не зависит от поддержки ГОСТ в OpenSSL.
"""

from __future__ import annotations

import logging
from typing import Any

from asn1crypto import cms, pem

from app.integrations.predreis.client import CertInfo
from app.integrations.predreis.signature import is_placeholder  # noqa: F401

logger = logging.getLogger(__name__)


def _owner(subject: Any) -> str:
    """ФИО владельца: CN, а если его нет — фамилия и имя-отчество, иначе весь subject."""
    native = subject.native
    cn = native.get("common_name")
    if cn:
        return str(cn)
    parts = [native.get("surname"), native.get("given_name")]
    joined = " ".join(str(p) for p in parts if p)
    return joined or str(subject.human_friendly)


def _serial_hex(serial: int) -> str:
    """Серийный номер целыми байтами (с ведущим нулём), как его показывает КриптоПро."""
    return serial.to_bytes((serial.bit_length() + 7) // 8 or 1, "big").hex()


def extract_cert_info(signature: bytes) -> CertInfo | None:
    """Возвращает серийный номер, владельца и срок действия сертификата подписанта или None."""
    try:
        if pem.detect(signature):
            _, _, signature = pem.unarmor(signature)
        signed = cms.ContentInfo.load(signature)["content"]
        certs = [c.chosen for c in signed["certificates"] if c.name == "certificate"]
        if not certs:
            return None
        serial = None
        sid = signed["signer_infos"][0]["sid"]
        if sid.name == "issuer_and_serial_number":
            serial = sid.chosen["serial_number"].native
        cert = next((c for c in certs if serial is None or c.serial_number == serial), certs[0])
        validity = cert["tbs_certificate"]["validity"]
        return CertInfo(
            serial=_serial_hex(cert.serial_number),
            subject=_owner(cert.subject),
            valid_from=validity["not_before"].native,
            valid_to=validity["not_after"].native,
        )
    except (ValueError, KeyError, IndexError, TypeError, AttributeError) as exc:
        logger.info("Не удалось разобрать сертификат из подписи: %s", type(exc).__name__)
        return None
