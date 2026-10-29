"""Подставной ПРЕДРЕЙС для разработки и сквозных проверок.

Повторяет контракт сервисного API: токен, вход пользователя, проверка пользователя, справочники,
асинхронная подпись (настоящие CMS-подписи тестовыми сертификатами) и публикация событий осмотров
в RabbitMQ. Запуск: `uvicorn tools.fake_predreis.app:app --port 9000`.

Параметры (переменные окружения): FAKE_CLIENT_SECRET (по умолчанию dev-secret), FAKE_SIGN_DELAY (с),
FAKE_RABBITMQ_URL, FAKE_QUEUE.
"""

from __future__ import annotations

import base64
import os
import secrets
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import aio_pika
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs7
from cryptography.x509.oid import NameOID
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from pydantic import BaseModel

from tools.fake_predreis import data

CLIENT_SECRET = os.environ.get("FAKE_CLIENT_SECRET", "dev-secret")
SIGN_DELAY = float(os.environ.get("FAKE_SIGN_DELAY", "3"))
RABBIT_URL = os.environ.get("FAKE_RABBITMQ_URL", "amqp://guest:guest@127.0.0.1:5672/")
QUEUE = os.environ.get("FAKE_QUEUE", "journal.events.outgoing")
EXCHANGE = "predreis.epl"
ROUTING_KEY = "journal.events"

app = FastAPI(title="Fake PREDREIS")
service_tokens: dict[str, float] = {}
user_tokens: dict[str, tuple[str, float]] = {}
sign_jobs: dict[str, dict[str, Any]] = {}
ORG_CERT_ID = data.uid("organization-predreis-kep")  # «пользователь» для КЭП организации в подставном Предрейсе
state: dict[str, Any] = {
    "sign_mode": "normal",
    "organizations": [dict(o) for o in data.ORGANIZATIONS],
}
_certs: dict[str, tuple[Any, x509.Certificate]] = {}


def _cert_for(user_id: str, name: str) -> tuple[Any, x509.Certificate]:
    """Тестовый сертификат пользователя (создаётся при первом обращении)."""
    if user_id not in _certs:
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)])
        now = datetime.now(timezone.utc)
        cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(subject)
            .public_key(key.public_key())
            .serial_number(int.from_bytes(uuid.UUID(user_id).bytes, "big") >> 4)
            .not_valid_before(now - timedelta(days=30))
            .not_valid_after(now + timedelta(days=700))
            .sign(key, hashes.SHA256())
        )
        _certs[user_id] = (key, cert)
    return _certs[user_id]


def _user_by_id(user_id: str) -> dict[str, Any] | None:
    """Пользователь по идентификатору."""
    return next((u for u in data.USERS.values() if u["id"] == user_id), None)


def service_auth(authorization: str | None = Header(default=None)) -> None:
    """Проверяет сервисный токен."""
    token = (authorization or "").removeprefix("Bearer ").strip()
    if service_tokens.get(token, 0) < time.time():
        raise HTTPException(401, "service token invalid")


# ---------- токен, вход, проверка пользователя ----------


class ServiceTokenIn(BaseModel):
    """Тело запроса сервисного токена."""

    client_id: str
    client_secret: str


@app.post("/api/v1/service/token")
def service_token(body: ServiceTokenIn) -> dict[str, Any]:
    """Выдаёт сервисный токен (30 минут)."""
    if body.client_id != "journals" or body.client_secret != CLIENT_SECRET:
        raise HTTPException(401, "bad client credentials")
    token = "st-" + secrets.token_hex(16)
    service_tokens[token] = time.time() + 1800
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": 1800,
        "scopes": [
            "epl_events:read",
            "orgs:read",
            "drivers:read",
            "vehicles:read",
            "sign:request",
            "users:verify",
        ],
    }


class LoginIn(BaseModel):
    """Почта и пароль."""

    email: str
    password: str


@app.post("/api/v1/auth/login")
def login(body: LoginIn) -> dict[str, Any]:
    """Вход пользователя ПРЕДРЕЙСа."""
    user = next((u for u in data.USERS.values() if u["email"] == body.email.lower()), None)
    if user is None or body.password != data.PASSWORD:
        raise HTTPException(401, "bad credentials")
    token = "ut-" + secrets.token_hex(16)
    user_tokens[token] = (user["id"], time.time() + 1800)
    return {"access_token": token, "token_type": "bearer", "expires_in": 1800}


class VerifyIn(BaseModel):
    """Токен пользователя для проверки."""

    access_token: str


@app.post("/api/v1/service/users/verify", dependencies=[Depends(service_auth)])
def verify(body: VerifyIn) -> dict[str, Any]:
    """Проверяет токен пользователя и флаг доступа к журналам."""
    entry = user_tokens.get(body.access_token)
    user = _user_by_id(entry[0]) if entry and entry[1] > time.time() else None
    if user is None or not user["is_active"]:
        raise HTTPException(401, "invalid token")
    if not user["journals_access"]:
        raise HTTPException(403, "Доступ к журналам не предоставлен")
    return {
        k: user[k]
        for k in (
            "id",
            "email",
            "last_name",
            "first_name",
            "middle_name",
            "role",
            "org_id",
            "journals_access",
            "is_active",
        )
    }


# ---------- сертификаты пользователей ----------


@app.get("/api/v1/service/certificates", dependencies=[Depends(service_auth)])
def certificates(role: str | None = None, user_id: str | None = None) -> list[dict[str, Any]]:
    """Сертификаты пользователей в формате образца Предрейса (ФИО частями, cert_cn, даты ДД.ММ.ГГГГ)."""
    out: list[dict[str, Any]] = []
    for user in data.USERS.values():
        if (role and user["role"] != role) or (user_id and user["id"] != user_id):
            continue
        name = f"{user['last_name']} {user['first_name']} {user['middle_name']}"
        item: dict[str, Any] = {
            "user_id": user["id"],
            "last_name": user["last_name"],
            "first_name": user["first_name"],
            "middle_name": user["middle_name"],
            "role": user["role"],
            "cert_cn": None,
            "thumbprint": None,
            "serial": None,
            "issuer": None,
            "valid_from": None,
            "valid_to": None,
            "is_valid": False,
        }
        if user["has_cert"]:
            _, cert = _cert_for(user["id"], name)
            item.update(
                cert_cn=f"{user['last_name']} {user['first_name']}",
                thumbprint=cert.fingerprint(hashes.SHA1()).hex(),
                serial="0x" + format(cert.serial_number, "X"),
                issuer='E=ca@test.ru, C=RU, CN="Тестовый удостоверяющий центр"',
                valid_from=cert.not_valid_before_utc.strftime("%d.%m.%Y"),
                valid_to=cert.not_valid_after_utc.strftime("%d.%m.%Y"),
                is_valid=True,
            )
        out.append(item)
    return out


# ---------- справочники ----------


def _catalog(
    rows: list[dict[str, Any]],
    changed_after: str | None,
    limit: int,
    offset: int,
    org_id: str | None,
) -> list[dict[str, Any]]:
    """Страница справочника: фильтр по времени изменения, сортировка по нему же."""
    out = sorted(rows, key=lambda r: (r["updated_at"], r["id"]))
    if changed_after:
        threshold = datetime.fromisoformat(changed_after.replace("Z", "+00:00"))
        out = [
            r
            for r in out
            if datetime.fromisoformat(r["updated_at"].replace("Z", "+00:00")) > threshold
        ]
    if org_id:
        out = [r for r in out if r.get("org_id") == org_id]
    return out[offset : offset + min(limit, 500)]


@app.get("/api/v1/service/catalogs/organizations", dependencies=[Depends(service_auth)])
def organizations(
    changed_after: str | None = None, limit: int = 100, offset: int = 0
) -> list[dict[str, Any]]:
    """Организации."""
    return _catalog(state["organizations"], changed_after, limit, offset, None)


@app.get("/api/v1/service/catalogs/drivers", dependencies=[Depends(service_auth)])
def drivers(
    changed_after: str | None = None, limit: int = 100, offset: int = 0, org_id: str | None = None
) -> list[dict[str, Any]]:
    """Водители."""
    return _catalog(data.DRIVERS, changed_after, limit, offset, org_id)


@app.get("/api/v1/service/catalogs/vehicles", dependencies=[Depends(service_auth)])
def vehicles(
    changed_after: str | None = None, limit: int = 100, offset: int = 0, org_id: str | None = None
) -> list[dict[str, Any]]:
    """ТС."""
    return _catalog(data.VEHICLES, changed_after, limit, offset, org_id)


# ---------- подпись (асинхронная) ----------


class SignIn(BaseModel):
    """Запрос подписи."""

    signer_user_id: str | None = None
    sign_as: str = "user"  # "organization" — КЭП организации ПРЕДРЕЙС (электронный журнал)
    requested_by_user_id: str | None = None
    document_type: str
    content_b64: str
    external_id: str


def _view(job: dict[str, Any]) -> dict[str, Any]:
    """Состояние задачи; подпись «выполняется» по истечении задержки."""
    if job["status"] == "pending" and time.time() - job["created"] >= SIGN_DELAY:
        mode = state["sign_mode"]
        if job.get("sign_as") == "organization":
            org = {
                "id": ORG_CERT_ID,
                "last_name": "ООО «ПРЕДРЕЙС»",
                "first_name": "",
                "middle_name": "",
                "has_cert": True,
            }
            user = org if mode != "fail" else None
        else:
            user = _user_by_id(job["signer_user_id"])
        if user is None or not user["has_cert"] or mode == "fail":
            job.update(
                status="failed",
                last_error=f"У специалиста {job['signer_user_id']} нет сертификата",
            )
        elif mode == "placeholder":
            job.update(status="signed", signature_b64="AUTO_SIGNATURE")
        else:
            key, cert = _cert_for(
                user["id"],
                f"{user['last_name']} {user['first_name']} {user['middle_name']}".strip(),
            )
            sig = (
                pkcs7.PKCS7SignatureBuilder()
                .set_data(base64.b64decode(job["content_b64"]))
                .add_signer(cert, key, hashes.SHA256())
                .sign(serialization.Encoding.DER, [pkcs7.PKCS7Options.DetachedSignature])
            )
            job.update(status="signed", signature_b64=base64.b64encode(sig).decode())
    return {k: job.get(k) for k in ("id", "status", "external_id", "signature_b64", "last_error")}


@app.post("/api/v1/service/sign", status_code=201, dependencies=[Depends(service_auth)])
def sign(body: SignIn) -> dict[str, Any]:
    """Принимает документ на подпись."""
    if len(body.content_b64) > 20 * 1024 * 1024 * 4 // 3:
        raise HTTPException(413, "content too large")
    if body.sign_as not in ("user", "organization"):
        raise HTTPException(422, "sign_as: user | organization")
    if body.sign_as == "user" and not body.signer_user_id:
        raise HTTPException(422, "signer_user_id обязателен при sign_as=user")
    job = {
        "id": str(uuid.uuid4()),
        "status": "pending",
        "external_id": body.external_id,
        "signature_b64": None,
        "last_error": None,
        "created": time.time(),
        "signer_user_id": body.signer_user_id,
        "sign_as": body.sign_as,
        "requested_by_user_id": body.requested_by_user_id,
        "content_b64": body.content_b64,
        "document_type": body.document_type,
    }
    sign_jobs[job["id"]] = job
    return _view(job)


@app.get("/api/v1/service/sign", dependencies=[Depends(service_auth)])
def sign_batch(external_ids: str) -> list[dict[str, Any]]:
    """Состояния задач пачкой."""
    wanted = set(external_ids.split(","))
    return [_view(j) for j in sign_jobs.values() if j["external_id"] in wanted]


@app.get("/api/v1/service/sign/{job_id}", dependencies=[Depends(service_auth)])
def sign_one(job_id: str) -> dict[str, Any]:
    """Состояние одной задачи."""
    if job_id not in sign_jobs:
        raise HTTPException(404, "not found")
    return _view(sign_jobs[job_id])


# ---------- управление стендом ----------


@app.post("/_dev/sign-mode/{mode}")
def set_sign_mode(mode: str) -> dict[str, str]:
    """normal | fail | placeholder — поведение подписи."""
    if mode not in {"normal", "fail", "placeholder"}:
        raise HTTPException(422, "mode")
    state["sign_mode"] = mode
    return {"sign_mode": mode}


@app.post("/_dev/touch-organization/{org_id}")
def touch_organization(org_id: str, name: str) -> dict[str, Any]:
    """Меняет организацию (для проверки инкрементальной синхронизации)."""
    for org in state["organizations"]:
        if org["id"] == org_id:
            org.update(name_short=name, updated_at=datetime.now(timezone.utc).isoformat())
            return org
    raise HTTPException(404, "organization")


@app.get("/_dev/users")
def dev_users() -> dict[str, Any]:
    """Тестовые пользователи (пароль у всех — password)."""
    return {
        k: {
            "email": v["email"],
            "id": v["id"],
            "role": v["role"],
            "journals_access": v["journals_access"],
        }
        for k, v in data.USERS.items()
    }


def _names(user: dict[str, Any]) -> dict[str, str]:
    """ФИО специалиста для события."""
    return {
        "last_name": user["last_name"],
        "first_name": user["first_name"],
        "middle_name": user["middle_name"],
    }


def _event(
    kind: str,
    waybill: str,
    org: dict[str, Any],
    driver: dict[str, Any],
    vehicle: dict[str, Any],
    specialist: dict[str, Any],
    when: datetime | None,
    title: int,
) -> dict[str, Any]:
    """Сообщение очереди в формате ПРЕДРЕЙСа (как в образцах)."""
    payload: dict[str, Any] = {
        "waybill_id": waybill,
        "waybill_number": waybill[:8].upper(),
        "gis_uid": str(uuid.uuid4()),
        "organization": {
            k: org[k]
            for k in ("id", "inn", "kpp", "ogrn", "name_short", "name_full", "legal_address")
        },
        "driver": {
            "id": driver["id"],
            **{k: driver[k] for k in ("last_name", "first_name", "middle_name", "gender")},
            "birth_date": driver["birth_date"][:10],
            "license_series": driver["license_series"],
            "license_number": driver["license_number"],
        },
        "vehicle": {
            "id": vehicle["id"],
            "plate_number": vehicle["plate_number"],
            "brand": vehicle["brand"],
            "model": vehicle["model"],
            "category": vehicle["category"],
        },
        "specialist_user_id": specialist["id"],
        "specialist": _names(specialist),
        "exam_datetime": when.isoformat() if when else None,
        "approved": True,
        "title_number": title,
        "title_doc_id": str(secrets.randbelow(10**9)),
    }
    if kind == "technical":
        payload.update(
            checks={"brakes_ok": True, "lighting_ok": True, "tires_ok": True},
            odometer=10000 + secrets.randbelow(5000),
            notes="Автоматический техосмотр (Водитель+)",
        )
    else:
        payload.update(
            exam_type="pre_trip" if title == 2 else "post_trip",
            vitals={
                "blood_pressure_systolic": 116,
                "blood_pressure_diastolic": 80,
                "pulse": 78,
                "temperature": 36.5,
                "alcohol_detected": False,
                "alcohol_ppm": 0.0,
            },
            complaints="отсутствуют",
            harmful_factors_detected=None,
            harmful_factors=None,
            critical_flag=False,
            notes="Автоматический осмотр (Водитель+)",
        )
    return {
        "id": str(uuid.uuid4()),
        "event_type": f"journal.{kind}_exam",
        "entity_id": waybill,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "payload": payload,
    }


async def _publish(events: list[dict[str, Any]]) -> None:
    """Публикует события в обменник (очередь и привязка создаются при необходимости)."""
    import json

    connection = await aio_pika.connect_robust(RABBIT_URL)
    async with connection:
        channel = await connection.channel()
        exchange = await channel.declare_exchange(
            EXCHANGE, aio_pika.ExchangeType.DIRECT, durable=True
        )
        queue = await channel.declare_queue(QUEUE, durable=True)
        await queue.bind(exchange, routing_key=ROUTING_KEY)
        for event in events:
            await exchange.publish(
                aio_pika.Message(
                    json.dumps(event, ensure_ascii=False).encode(),
                    delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
                ),
                routing_key=ROUTING_KEY,
            )


class PublishIn(BaseModel):
    """Сколько рейсов опубликовать и какие «особые» события добавить."""

    waybills: int = 1
    old_technical_without_time: bool = False
    base_time: str | None = None


@app.on_event("startup")
async def declare_queue() -> None:
    """Создаёт обменник и очередь заранее: потребитель журналов объявляет её пассивно."""
    try:
        await _publish([])
    except Exception as exc:
        print(f"RabbitMQ недоступен, события публиковаться не будут: {exc}")


@app.post("/_dev/publish")
async def publish(body: PublishIn, request: Request) -> dict[str, Any]:
    """Публикует по каждому рейсу предрейсовый, послерейсовый осмотр и техконтроль."""
    org = state["organizations"][0]
    base = (
        datetime.fromisoformat(body.base_time)
        if body.base_time
        else datetime.now(timezone.utc) - timedelta(hours=3)
    )
    events = []
    for n in range(body.waybills):
        waybill = str(uuid.uuid4())
        driver = data.DRIVERS[n % 3]
        vehicle = data.VEHICLES[n % 2]
        when = base + timedelta(minutes=10 * n)
        events += [
            _event("medical", waybill, org, driver, vehicle, data.USERS["medic"], when, 2),
            _event(
                "technical",
                waybill,
                org,
                driver,
                vehicle,
                data.USERS["mechanic"],
                when + timedelta(minutes=5),
                3,
            ),
            _event(
                "medical",
                waybill,
                org,
                driver,
                vehicle,
                data.USERS["medic"],
                when + timedelta(hours=1),
                6,
            ),
        ]
    if body.old_technical_without_time:
        events.append(
            _event(
                "technical",
                str(uuid.uuid4()),
                org,
                data.DRIVERS[0],
                data.VEHICLES[0],
                data.USERS["mechanic"],
                None,
                3,
            )
        )
    await _publish(events)
    return {"published": len(events), "ids": [e["id"] for e in events]}
