from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import os
import time
import uuid
import unicodedata
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx
import websockets
from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import RedirectResponse, StreamingResponse, JSONResponse
from starlette.websockets import WebSocketDisconnect


UPSTREAM = os.environ.get("SCANNTECH_UPSTREAM", "http://127.0.0.1:3000")
PORTAL_GATEWAY = os.environ.get(
    "SCANNTECH_GATEWAY_URL",
    "http://192.168.8.123:9090/sistemas/comercial/scanntech.php",
)
SECRET_FILE = os.environ.get(
    "SCANNTECH_SSO_SECRET_FILE",
    r"C:\xampp\private\aquafast\scanntech_sso.key",
)
BIND_HOST = os.environ.get("SCANNTECH_PROXY_HOST", "127.0.0.1")
BIND_PORT = int(os.environ.get("SCANNTECH_PROXY_PORT", "3001"))
SESSION_COOKIE = os.environ.get("SCANNTECH_SESSION_COOKIE", "aqf_scanntech_sso")
SESSION_TTL = int(os.environ.get("SCANNTECH_SESSION_TTL", "300"))
PUBLIC_BASE_PATH = os.environ.get("SCANNTECH_PUBLIC_BASE_PATH", "/")

HEADER_EMAIL = "X-Forwarded-Email"
HEADER_NAME = "X-Forwarded-Name"
HEADER_GROUPS = "X-Forwarded-Groups"
STRIP_HEADERS = {
    "authorization",
    "x-forwarded-user",
    "x-forwarded-email",
    "x-forwarded-name",
    "x-forwarded-role",
    "x-forwarded-groups",
}

log = logging.getLogger("scanntech_proxy")
app = FastAPI(title="Scanntech SSO Proxy", docs_url=None, redoc_url=None)


@dataclass
class Claims:
    sub: str
    email: str
    name: str
    perfil: str
    groups: list[str]
    iat: int
    exp: int
    jti: str


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64url_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def _read_secret() -> str:
    with open(SECRET_FILE, "r", encoding="utf-8") as handle:
        secret = handle.read().strip()
    if not secret:
        raise RuntimeError("Secret SSO vazio.")
    return secret


def _sign(payload_b64: str, secret: str) -> str:
    signature = hmac.new(
        secret.encode("utf-8"),
        payload_b64.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return _b64url_encode(signature)


def _encode_token(payload: dict[str, Any], secret: str) -> str:
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    payload_b64 = _b64url_encode(raw)
    return f"{payload_b64}.{_sign(payload_b64, secret)}"


def _decode_token(token: str, secret: str) -> Claims:
    payload_b64, signature = token.split(".", 1)
    expected = _sign(payload_b64, secret)
    if not hmac.compare_digest(expected, signature):
        raise ValueError("assinatura invalida")

    payload = json.loads(_b64url_decode(payload_b64))
    now = int(time.time())
    iat = int(payload["iat"])
    exp = int(payload["exp"])
    if now < iat or now > exp:
        raise ValueError("ticket expirado")

    groups = payload.get("groups", [])
    if not isinstance(groups, list):
        groups = []

    return Claims(
        sub=str(payload["sub"]),
        email=str(payload["email"]),
        name=str(payload["name"]),
        perfil=str(payload["perfil"]),
        groups=[str(item) for item in groups],
        iat=iat,
        exp=exp,
        jti=str(payload["jti"]),
    )


def _mint_session_cookie(claims: Claims, secret: str) -> str:
    now = int(time.time())
    payload = {
        "sub": claims.sub,
        "email": claims.email,
        "name": claims.name,
        "perfil": claims.perfil,
        "groups": claims.groups,
        "iat": now,
        "exp": now + SESSION_TTL,
        "jti": str(uuid.uuid4()),
    }
    return _encode_token(payload, secret)


def _ascii_header_value(value: str, fallback: str = "") -> str:
    if not value:
        return fallback
    try:
        value.encode("ascii")
        return value
    except UnicodeEncodeError:
        normalized = unicodedata.normalize("NFKD", value)
        ascii_value = normalized.encode("ascii", "ignore").decode("ascii").strip()
        return ascii_value or fallback


def _forward_headers(claims: Claims, raw_headers: dict[str, str]) -> dict[str, str]:
    headers: dict[str, str] = {}
    for key, value in raw_headers.items():
        if key.lower() in STRIP_HEADERS:
            continue
        if key.lower() in {
            "host",
            "content-length",
            "connection",
            "upgrade",
            "proxy-connection",
            "accept-encoding",
        }:
            continue
        try:
            value.encode("ascii")
        except UnicodeEncodeError:
            # httpx requires ASCII header values; drop invalid inbound values.
            continue
        headers[key] = value

    # Force identity encoding so upstream returns plain content and avoids
    # compressed body/header mismatch at the proxy boundary.
    headers["Accept-Encoding"] = "identity"
    headers[HEADER_EMAIL] = _ascii_header_value(claims.email, "unknown@local")
    headers[HEADER_NAME] = _ascii_header_value(claims.name, "Usuario")
    sanitized_groups = [_ascii_header_value(group) for group in claims.groups]
    sanitized_groups = [group for group in sanitized_groups if group]
    headers[HEADER_GROUPS] = ",".join(sanitized_groups) if sanitized_groups else "comercial"
    return headers


def _verify_cookie(cookie: str, secret: str) -> Claims:
    return _decode_token(cookie, secret)


def _normalize_path(path: str) -> str:
    if not path.startswith("/"):
        path = "/" + path
    return path


def _normalize_base_path(path: str) -> str:
    path = "/" + path.strip("/")
    return path if path != "/" else ""


def _to_public_path(path: str) -> str:
    base = _normalize_base_path(PUBLIC_BASE_PATH)
    normalized = _normalize_path(path)
    if not base:
        return normalized
    if normalized == "/":
        return base + "/"
    return base + normalized


def _to_upstream_path(path: str) -> str:
    normalized = _normalize_path(path)
    base = _normalize_base_path(PUBLIC_BASE_PATH)
    if not base:
        return normalized

    if normalized == base:
        return "/"
    if normalized.startswith(base + "/"):
        stripped = normalized[len(base) :]
        return stripped if stripped else "/"
    return normalized


def _rewrite_location(location: str) -> str:
    if not location:
        return location

    if location.startswith(UPSTREAM):
        location = location[len(UPSTREAM) :]
        if not location.startswith("/"):
            location = "/" + location

    if location.startswith("/"):
        base = _normalize_base_path(PUBLIC_BASE_PATH)
        if base and (location == base or location.startswith(base + "/")):
            return location
        return _to_public_path(location)
    return location


@app.on_event("startup")
async def _startup() -> None:
    app.state.secret = _read_secret()
    app.state.client = httpx.AsyncClient(timeout=None, follow_redirects=False)


@app.on_event("shutdown")
async def _shutdown() -> None:
    await app.state.client.aclose()


@app.get("/health")
async def health() -> JSONResponse:
    return JSONResponse({"ok": True})


@app.api_route("/{full_path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"])
async def proxy_http(full_path: str, request: Request):
    secret: str = app.state.secret
    ticket = request.query_params.get("sso_ticket")

    if ticket:
        try:
            claims = _decode_token(ticket, secret)
        except Exception:
            response = RedirectResponse(url=PORTAL_GATEWAY, status_code=302)
            response.delete_cookie(SESSION_COOKIE, path="/")
            return response
        session_cookie = _mint_session_cookie(claims, secret)
        clean_query = [(k, v) for k, v in request.query_params.multi_items() if k != "sso_ticket"]
        target = _to_public_path(full_path)
        if clean_query:
            target = f"{target}?{urlencode(clean_query, doseq=True)}"
        response = RedirectResponse(url=target, status_code=302)
        response.set_cookie(
            key=SESSION_COOKIE,
            value=session_cookie,
            httponly=True,
            samesite="Lax",
            secure=False,
            max_age=SESSION_TTL,
            path="/",
        )
        log.info("ticket accepted jti=%s sub=%s email=%s", claims.jti, claims.sub, claims.email)
        return response

    cookie = request.cookies.get(SESSION_COOKIE)
    if not cookie:
        return RedirectResponse(url=PORTAL_GATEWAY, status_code=302)

    try:
        claims = _verify_cookie(cookie, secret)
    except Exception:
        response = RedirectResponse(url=PORTAL_GATEWAY, status_code=302)
        response.delete_cookie(SESSION_COOKIE, path="/")
        return response

    upstream_path = _to_upstream_path(full_path)
    upstream_url = httpx.URL(UPSTREAM).copy_with(path=upstream_path, query=request.url.query.encode("utf-8"))
    body = await request.body()
    headers = _forward_headers(claims, dict(request.headers))

    upstream_request = app.state.client.build_request(
        method=request.method,
        url=upstream_url,
        content=body if body else None,
        headers=headers,
    )
    upstream_response = await app.state.client.send(upstream_request, stream=True)

    response_headers = {}
    for key, value in upstream_response.headers.items():
        lower = key.lower()
        if lower in {"content-length", "transfer-encoding", "connection"}:
            continue
        response_headers[key] = value

    location = response_headers.get("location")
    if location:
        response_headers["location"] = _rewrite_location(location)

    async def body_iter():
        try:
            async for chunk in upstream_response.aiter_raw():
                yield chunk
        finally:
            await upstream_response.aclose()

    return StreamingResponse(
        body_iter(),
        status_code=upstream_response.status_code,
        headers=response_headers,
        media_type=upstream_response.headers.get("content-type"),
    )


@app.websocket("/{full_path:path}")
async def proxy_websocket(websocket: WebSocket, full_path: str):
    secret: str = app.state.secret
    await websocket.accept()

    cookie = websocket.cookies.get(SESSION_COOKIE)
    if not cookie:
        await websocket.close(code=4401)
        return

    try:
        claims = _verify_cookie(cookie, secret)
    except Exception:
        await websocket.close(code=4401)
        return

    ws_url = httpx.URL(UPSTREAM).copy_with(
        scheme="ws" if UPSTREAM.startswith("http://") else "wss",
        path=_to_upstream_path(full_path),
        query=websocket.url.query.encode("utf-8"),
    )
    headers = _forward_headers(claims, {})

    try:
        async with websockets.connect(
            str(ws_url),
            additional_headers=headers,
            ping_interval=20,
            ping_timeout=20,
        ) as upstream_ws:
            async def client_to_upstream() -> None:
                while True:
                    message = await websocket.receive()
                    if message["type"] == "websocket.disconnect":
                        break
                    text = message.get("text")
                    data = message.get("bytes")
                    if text is not None:
                        await upstream_ws.send(text)
                    elif data is not None:
                        await upstream_ws.send(data)

            async def upstream_to_client() -> None:
                async for message in upstream_ws:
                    if isinstance(message, str):
                        await websocket.send_text(message)
                    else:
                        await websocket.send_bytes(message)

            await asyncio.gather(client_to_upstream(), upstream_to_client())
    except WebSocketDisconnect:
        return
    except Exception as exc:
        log.warning("websocket proxy failed: %s", exc)
        await websocket.close(code=1011)


def main() -> None:
    import uvicorn

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    uvicorn.run(
        "sso_proxy:app",
        host=BIND_HOST,
        port=BIND_PORT,
        reload=False,
        log_level="info",
        access_log=False,
    )


if __name__ == "__main__":
    main()

