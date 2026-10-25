"""Сведения о сертификате берутся из самой подписи CMS (без полей в ответе Предрейса)."""

from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone

from asn1crypto import cms
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs7
from cryptography.x509.oid import NameOID

from app.integrations.predreis.cms import extract_cert_info


def make_signature(
    cn: str = "Абдуллаева Гульзана Абутдиновна",
    encoding: serialization.Encoding = serialization.Encoding.DER,
) -> tuple[bytes, x509.Certificate]:
    """Откреплённая подпись CMS тестовым сертификатом."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])
    now = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(0x0F18DD73747ECCC4AB0D2B1EE00D4040)
        .not_valid_before(now - timedelta(days=10))
        .not_valid_after(now + timedelta(days=355))
        .sign(key, hashes.SHA256())
    )
    sig = (
        pkcs7.PKCS7SignatureBuilder()
        .set_data(b"content")
        .add_signer(cert, key, hashes.SHA256())
        .sign(encoding, [pkcs7.PKCS7Options.DetachedSignature])
    )
    return sig, cert


def test_extracts_serial_owner_and_validity() -> None:
    """Серийный номер, владелец и срок действия совпадают с сертификатом."""
    sig, cert = make_signature()
    info = extract_cert_info(sig)
    assert info is not None
    assert info.serial == "0f18dd73747eccc4ab0d2b1ee00d4040"  # 16 байт, как показывает КриптоПро
    assert info.subject == "Абдуллаева Гульзана Абутдиновна"
    assert (
        info.valid_from == cert.not_valid_before_utc and info.valid_to == cert.not_valid_after_utc
    )


def test_pem_signature_is_supported() -> None:
    """Подпись в PEM тоже разбирается."""
    sig, cert = make_signature(encoding=serialization.Encoding.PEM)
    info = extract_cert_info(sig)
    assert info is not None and info.serial == cert.serial_number.to_bytes(16, "big").hex()


def test_garbage_returns_none() -> None:
    """Не подпись — None, без исключений."""
    assert extract_cert_info(b"not a signature") is None
    assert extract_cert_info(b"") is None
    assert extract_cert_info(base64.b64decode(base64.b64encode(b"\x30\x03\x02\x01\x00"))) is None


def test_ber_with_indefinite_length_like_predreis() -> None:
    """Подпись Предрейса — BER с неопределённой длиной (начинается с 30 80); разбирается так же."""
    der, cert = make_signature()
    info = cms.ContentInfo.load(der)
    ber = (
        b"\x30\x80" + info["content_type"].dump() + b"\xa0\x80" + b"\x30\x80"
        + info["content"].contents + b"\x00\x00" * 3
    )  # fmt: skip
    assert ber[:2] == b"\x30\x80"
    parsed = extract_cert_info(ber)
    assert parsed is not None and parsed.subject == "Абдуллаева Гульзана Абутдиновна"
    assert parsed.serial == cert.serial_number.to_bytes(16, "big").hex()
    # Та же подпись в base64, как приходит в signature_b64.
    assert extract_cert_info(base64.b64decode(base64.b64encode(ber))) == parsed
