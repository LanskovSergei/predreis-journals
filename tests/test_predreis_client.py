"""Клиент Предрейса: сервисный токен, справочники, асинхронная подпись (на подставном HTTP)."""

from __future__ import annotations

import base64
import json
import uuid
from datetime import datetime, timezone

import httpx
import pytest

from app.core.config import Settings
from app.core.errors import ForbiddenError, UnauthorizedError, UpstreamError
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


# ---------- вход и проверка пользователя ----------

VERIFIED = {
    "id": "13a3aa8c-8d2c-4509-8676-9955f8e332d4",
    "email": "user@example.ru",
    "last_name": "Иванов",
    "first_name": "Иван",
    "middle_name": "Иванович",
    "role": "superadmin",
    "org_id": None,
    "journals_access": True,
    "is_active": True,
}


class UsersServer(Server):
    """Подставной Предрейс с проверкой пользователей и входом."""

    def __init__(self) -> None:
        """Сценарии ответов."""
        super().__init__()
        self.verify_status = 200
        self.verify_detail = "Доступ к журналам не предоставлен"
        self.login_response: httpx.Response | None = None
        self.verify_requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        """Обрабатывает запрос."""
        if request.url.path == "/api/v1/service/users/verify":
            self.requests.append(request)
            self.verify_requests.append(request)
            if self.reject_next:
                self.reject_next = False
                return httpx.Response(401, json={"detail": "service token expired"})
            if self.verify_status == 200:
                return httpx.Response(200, json=VERIFIED)
            return httpx.Response(self.verify_status, json={"detail": self.verify_detail})
        if request.url.path == "/api/v1/auth/login":
            self.requests.append(request)
            return self.login_response or httpx.Response(200, json={"access_token": "user-token"})
        return super().__call__(request)


async def test_verify_user_success_sends_service_token_and_user_token() -> None:
    """Проверка: сервисный токен в заголовке, токен пользователя в теле; ответ разобран."""
    srv = UsersServer()
    user = await make_client(httpx.MockTransport(srv)).verify_user("user-token-xyz")
    req = srv.verify_requests[-1]
    assert req.headers["authorization"] == "Bearer tok1"
    assert json.loads(req.content) == {"access_token": "user-token-xyz"}
    assert user.role == "superadmin" and user.full_name == "Иванов Иван Иванович"
    assert user.org_id is None and user.journals_access is True


async def test_verify_user_refreshes_service_token_once() -> None:
    """401 из-за истёкшего сервисного токена: берём новый и повторяем, пользователь не страдает."""
    srv = UsersServer()
    client = make_client(httpx.MockTransport(srv))
    await client.verify_user("t")
    srv.reject_next = True
    assert (await client.verify_user("t")).journals_access is True
    assert srv.tokens == 2


async def test_verify_user_invalid_token_is_unauthorized() -> None:
    """401 и после обновления сервисного токена — токен пользователя недействителен."""
    srv = UsersServer()
    srv.verify_status = 401
    with pytest.raises(UnauthorizedError):
        await make_client(httpx.MockTransport(srv)).verify_user("bad")
    assert srv.tokens == 2  # один раз попробовали обновить сервисный токен


async def test_verify_user_without_journals_access_is_forbidden() -> None:
    """403 «Доступ к журналам не предоставлен» → отказ с кодом journals_disabled."""
    srv = UsersServer()
    srv.verify_status = 403
    with pytest.raises(ForbiddenError) as exc:
        await make_client(httpx.MockTransport(srv)).verify_user("t")
    assert exc.value.code == "journals_disabled"


async def test_verify_user_403_for_other_reason_is_service_misconfiguration() -> None:
    """403 по другой причине (у сервиса нет права users:verify) — ошибка интеграции, не отказ пользователю."""
    srv = UsersServer()
    srv.verify_status, srv.verify_detail = 403, "Недостаточно прав: users:verify"
    with pytest.raises(UpstreamError):
        await make_client(httpx.MockTransport(srv)).verify_user("t")


async def test_user_login_returns_token_and_never_sends_service_token() -> None:
    """Вход: почта и пароль уходят в Предрейс без сервисного токена; пароль не попадает в ошибки."""
    srv = UsersServer()
    login = await make_client(httpx.MockTransport(srv)).user_login("a@e.ru", SECRET)
    req = srv.requests[-1]
    assert login.access_token == "user-token" and "authorization" not in req.headers
    assert json.loads(req.content) == {"email": "a@e.ru", "password": SECRET}

    srv.login_response = httpx.Response(401, json={"detail": "bad"})
    with pytest.raises(UnauthorizedError) as exc:
        await make_client(httpx.MockTransport(srv)).user_login("a@e.ru", SECRET)
    assert exc.value.code == "invalid_credentials" and SECRET not in str(exc.value)


async def test_user_login_token_from_cookie_and_server_errors() -> None:
    """Токен может прийти в cookie; 5xx — ошибка интеграции."""
    srv = UsersServer()
    srv.login_response = httpx.Response(
        200, json={}, headers={"set-cookie": "access_token=cookie-tok; Path=/"}
    )
    assert (
        await make_client(httpx.MockTransport(srv)).user_login("a@e.ru", "p")
    ).access_token == "cookie-tok"
    srv.login_response = httpx.Response(500)
    with pytest.raises(UpstreamError):
        await make_client(httpx.MockTransport(srv)).user_login("a@e.ru", "p")
    srv.login_response = httpx.Response(200, json={"foo": 1})
    with pytest.raises(UpstreamError):
        await make_client(httpx.MockTransport(srv)).user_login("a@e.ru", "p")


def test_placeholder_signature_in_sign_result_is_a_refusal() -> None:
    """Заглушка AUTO_SIGNATURE в результате подписи не принимается за подпись."""
    status = parse_sign_status(
        {"id": "1", "external_id": "e", "status": "signed", "signature_b64": "AUTO_SIGNATURE"}
    )
    assert status.status == "failed" and status.signature is None
    assert "AUTO_SIGNATURE" in (status.error or "")


def test_garbage_signature_in_sign_result_is_upstream_error() -> None:
    """Подпись не в base64 — ошибка интеграции, а не необработанное исключение."""
    with pytest.raises(UpstreamError):
        parse_sign_status(
            {"id": "1", "external_id": "e", "status": "signed", "signature_b64": "%%%"}
        )


async def test_submit_as_organization_matches_agreed_contract() -> None:
    """Подпись журнала КЭП организации: sign_as=organization, без signer_user_id, с инициатором."""
    srv = Server()
    client = make_client(httpx.MockTransport(srv))
    sa = uuid.uuid4()
    await client.submit(
        signer_user_id=None,
        document_type="journal.ejournal",
        content=b"<journal/>",
        external_id="j1",
        sign_as="organization",
        requested_by_user_id=sa,
    )
    sent = json.loads(
        [r for r in srv.requests if r.method == "POST" and "sign" in r.url.path][-1].content
    )
    assert sent == {
        "sign_as": "organization",
        "document_type": "journal.ejournal",
        "content_b64": base64.b64encode(b"<journal/>").decode(),
        "external_id": "j1",
        "requested_by_user_id": str(sa),
    }


async def test_submit_as_user_requires_signer() -> None:
    """Подпись специалистом без специалиста не уходит в Предрейс (там это 422)."""
    srv = Server()
    client = make_client(httpx.MockTransport(srv))
    with pytest.raises(ValueError):
        await client.submit(signer_user_id=None, document_type="x", content=b"x", external_id="e")
    assert not [r for r in srv.requests if "sign" in r.url.path]
