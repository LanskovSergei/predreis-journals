"""Клиент Предрейса: сервисный токен, справочники, асинхронная подпись (на подставном HTTP)."""

from __future__ import annotations

import base64
import json
import uuid
from datetime import datetime, timezone

import httpx
import pytest

from app.core.config import Settings
from app.core.errors import UpstreamError
from app.integrations.predreis.client import PredreisClient, parse_sign_status
from tests.samples.predreis import load

SECRET = "super-secret-value-123"


def make_client(handler: httpx.MockTransport) -> PredreisClient:
    """Клиент с подставным транспортом."""
    settings = Settings(
        predreis_base_url="https://predreis.test",
        predreis_client_id="journals",
        predreis_client_secret=SECRET,
    )
    http = httpx.AsyncClient(transport=handler, base_url="https://predreis.test")
    return PredreisClient(settings, http)


class Server:
    """Подставной Предрейс: выдаёт токены и записывает запросы."""

    def __init__(self) -> None:
        """Счётчики и журнал запросов."""
        self.tokens = 0
        self.requests: list[httpx.Request] = []
        self.reject_next = False

    def __call__(self, request: httpx.Request) -> httpx.Response:
        """Обрабатывает запрос."""
        self.requests.append(request)
        if request.url.path == "/api/v1/service/token":
            self.tokens += 1
            body = json.loads(request.content)
            if body["client_secret"] != SECRET:
                return httpx.Response(401, json={"detail": "bad secret"})
            return httpx.Response(
                200, json={"access_token": f"tok{self.tokens}", "expires_in": 1800}
            )
        if self.reject_next:
            self.reject_next = False
            return httpx.Response(401, json={"detail": "expired"})
        path = request.url.path
        if path.startswith("/api/v1/service/catalogs/"):
            return httpx.Response(200, json={"items": [{"id": "x"}], "total": 1})
        if path == "/api/v1/service/sign" and request.method == "POST":
            return httpx.Response(201, json=load("sign_submit_response.json"))
        if path == "/api/v1/service/sign":
            return httpx.Response(
                200,
                json=[
                    {"id": "s1", "external_id": "e1", "status": "signed",
                     "signature_b64": base64.b64encode(b"SIG").decode()},
                    {"id": "s2", "external_id": "e2", "status": "failed", "last_error": "сертификат истёк"},
                    {"id": "s3", "external_id": "e3", "status": "pending"},
                ],
            )  # fmt: skip
        return httpx.Response(404)


async def test_token_is_cached_and_sent_as_bearer() -> None:
    """Токен получается один раз и передаётся в заголовке; секрет уходит только в запрос токена."""
    srv = Server()
    client = make_client(httpx.MockTransport(srv))
    await client.list_catalog("organizations")
    await client.list_catalog("drivers")
    assert srv.tokens == 1
    api = [r for r in srv.requests if "/catalogs/" in r.url.path]
    assert all(r.headers["authorization"] == "Bearer tok1" for r in api)
    assert all(SECRET.encode() not in r.content and SECRET not in str(r.url) for r in api)


async def test_token_is_refreshed_once_on_401() -> None:
    """Если Предрейс отклонил токен, клиент один раз берёт новый и повторяет запрос."""
    srv = Server()
    client = make_client(httpx.MockTransport(srv))
    await client.list_catalog("vehicles")
    srv.reject_next = True
    await client.list_catalog("vehicles")
    assert srv.tokens == 2


async def test_bad_secret_error_does_not_leak_secret() -> None:
    """Ошибка получения токена не содержит секрета."""
    settings = Settings(predreis_client_secret="wrong-secret-xyz")
    srv = Server()
    client = PredreisClient(
        settings, httpx.AsyncClient(transport=httpx.MockTransport(srv), base_url="https://p.test")
    )
    with pytest.raises(UpstreamError) as exc:
        await client.list_catalog("organizations")
    assert "wrong-secret-xyz" not in str(exc.value) and "wrong-secret-xyz" not in repr(
        exc.value.details
    )


async def test_catalog_params_and_response_shapes() -> None:
    """Параметры changed_after/limit/offset/org_id передаются; ответ — список или {items}."""
    srv = Server()
    client = make_client(httpx.MockTransport(srv))
    org = uuid.uuid4()
    when = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
    items = await client.list_catalog(
        "drivers", changed_after=when, limit=9999, offset=40, org_id=org
    )
    assert items == [{"id": "x"}]
    q = dict(srv.requests[-1].url.params)
    assert q["limit"] == "500" and q["offset"] == "40" and q["org_id"] == str(org)
    assert q["changed_after"].startswith("2026-10-01T12:00:00")


async def test_submit_and_fetch_sign() -> None:
    """Отправка на подпись и пакетный опрос: статусы разбираются, содержимое — base64."""
    srv = Server()
    client = make_client(httpx.MockTransport(srv))
    signer = uuid.uuid4()
    ticket = await client.submit(
        signer_user_id=signer,
        document_type="journal.medical_exam",
        content=b"<xml/>",
        external_id="e1",
    )
    assert ticket.sign_id == "935e54ab-b06c-42e7-b902-c15bef8ec8d2" and ticket.status == "pending"
    sent = json.loads(
        [r for r in srv.requests if r.method == "POST" and "sign" in r.url.path][-1].content
    )
    assert (
        sent["signer_user_id"] == str(signer)
        and base64.b64decode(sent["content_b64"]) == b"<xml/>"
    )
    assert sent["external_id"] == "e1" and sent["document_type"] == "journal.medical_exam"

    statuses = {s.external_id: s for s in await client.fetch(["e1", "e2", "e3"])}
    assert srv.requests[-1].url.params["external_ids"] == "e1,e2,e3"
    assert statuses["e1"].status == "signed" and statuses["e1"].signature == b"SIG"
    assert statuses["e2"].status == "failed" and statuses["e2"].error == "сертификат истёк"
    assert statuses["e3"].status == "pending" and statuses["e3"].signature is None


def test_unknown_sign_status_rejected() -> None:
    """Неизвестный статус подписи не принимается молча."""
    with pytest.raises(UpstreamError):
        parse_sign_status({"id": "1", "external_id": "e", "status": "weird"})


async def test_server_error_becomes_upstream_error() -> None:
    """5xx и сетевые сбои превращаются в UpstreamError."""

    def boom(request: httpx.Request) -> httpx.Response:
        """Токен выдаётся, а сервис падает."""
        if request.url.path.endswith("/token"):
            return httpx.Response(200, json={"access_token": "t", "expires_in": 1800})
        raise httpx.ConnectError("нет связи")

    with pytest.raises(UpstreamError):
        await make_client(httpx.MockTransport(boom)).list_catalog("organizations")


def test_real_sign_samples_are_parsed() -> None:
    """Реальные ответы подписи: принятая задача и отказ с причиной."""
    pending = parse_sign_status(load("sign_submit_response.json"))
    assert pending.status == "pending" and pending.signature is None
    assert pending.external_id == "journal-record-12345"
    failed = parse_sign_status(load("sign_failed.json"))
    assert failed.status == "failed" and "нет сертификата" in (failed.error or "")


def test_real_token_response_shape() -> None:
    """Ответ токена: access_token и expires_in, как в образце."""
    sample = load("token.json")
    assert sample["token_type"] == "bearer" and sample["expires_in"] == 1800
