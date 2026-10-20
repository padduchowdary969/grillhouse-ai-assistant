"""Copilot backend: authentication, rate limits, request logging and the copilot's tools as HTTP endpoints.

Run from the project root:
    uvicorn app.api:app --port 8000          # docs at http://localhost:8000/docs

Sign in with POST /auth/token to get a bearer token; it carries a role (owner or staff) for role-based access.
The phone app (ui/static) is served from / and signs in with POST /login, which puts the same kind of token
in an HttpOnly cookie instead.

For the shop's private deployment, set GRILLHOUSE_ALLOWED_NETWORKS=private so only this computer and the
Tailscale network can connect.
"""

import hmac
import ipaddress
import json
import os
import queue
import secrets
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from app import chatbot
from app import config  # noqa: F401  (loads .env)
from app.documents import search
from app.sql_tool import run
from app.text_to_sql import ask

JWT_SECRET = os.environ.get("GRILLHOUSE_JWT_SECRET", "")
TOKEN_HOURS = 12
# Passwords per role; staff is optional until the staff view exists
ROLE_PASSWORDS = {"owner": os.environ.get("GRILLHOUSE_PASSWORD", ""),
                  "staff": os.environ.get("GRILLHOUSE_STAFF_PASSWORD", "")}
RATE_LIMIT = int(os.environ.get("GRILLHOUSE_RATE_LIMIT", "20"))  # model-backed requests per user per minute
LOG = Path(os.environ.get("GRILLHOUSE_REQUEST_LOG", "logs/requests.jsonl"))
COOKIE, COOKIE_DAYS = "grillhouse_session", 30  # phones stay signed in for a month
MAX_FAILED_LOGINS = 10  # per run, then sign-in locks until the server restarts
UI = Path(__file__).resolve().parent.parent / "ui" / "static"
# "private" = this computer + Tailscale (100.64.0.0/10, fd7a:115c:a1e0::/48); unset = any network
NETWORKS = {"private": ["127.0.0.0/8", "::1/128", "100.64.0.0/10", "fd7a:115c:a1e0::/48"]}
_allowed = os.environ.get("GRILLHOUSE_ALLOWED_NETWORKS", "")
ALLOWED_NETWORKS = [ipaddress.ip_network(n) for n in NETWORKS.get(_allowed, _allowed.split(",") if _allowed else [])]

app = FastAPI(title="Grill House Ops Copilot", version="0.2.0",
              description="AI analyst for a late-night takeaway: Text-to-SQL over sales and deliveries, cited menu "
                          "and policy search. Demo data is synthetic.")
bearer = HTTPBearer(auto_error=False)
recent_requests: dict[str, deque] = defaultdict(deque)
failed_logins = {"count": 0}
chat_histories: dict[str, list[dict]] = {}  # per sign-in session, so two phones don't share a conversation
model_lock = threading.Lock()  # the local model answers one question at a time


# ---------- auth ----------

class TokenRequest(BaseModel):
    password: str = Field(max_length=200)


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    expires_at: datetime


def issue(role: str, hours: float = TOKEN_HOURS) -> Token:
    expires = datetime.now(timezone.utc) + timedelta(hours=hours)
    claims = {"sub": role, "role": role, "sid": secrets.token_urlsafe(12), "exp": expires}
    return Token(access_token=jwt.encode(claims, JWT_SECRET, algorithm="HS256"), role=role, expires_at=expires)


def current_user(request: Request, credentials: HTTPAuthorizationCredentials | None = Depends(bearer)) -> dict:
    """Bearer token for API clients, or the session cookie for the phone app."""
    token = credentials.credentials if credentials else request.cookies.get(COOKIE)
    if not token:
        raise HTTPException(401, "Sign in at /auth/token first", headers={"WWW-Authenticate": "Bearer"})
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(401, "Invalid or expired token", headers={"WWW-Authenticate": "Bearer"}) from None


def check_password(password: str) -> str:
    """Return the role for this password, counting failures towards the lockout."""
    if not JWT_SECRET:
        raise HTTPException(500, "Server not configured: set GRILLHOUSE_JWT_SECRET")
    if failed_logins["count"] >= MAX_FAILED_LOGINS:
        raise HTTPException(429, "Too many wrong passwords. Restart the assistant to try again.")
    for role, expected in ROLE_PASSWORDS.items():
        if len(expected) >= 8 and hmac.compare_digest(password.encode(), expected.encode()):
            return role
    failed_logins["count"] += 1
    raise HTTPException(401, "Wrong password.")


def owner_only(user: dict = Depends(current_user)) -> dict:
    if user["role"] != "owner":
        raise HTTPException(403, "Owners only")
    return user


def rate_limited(user: dict = Depends(current_user)) -> dict:
    """Sliding one-minute window per user, for endpoints that call a model."""
    window, now = recent_requests[user["sub"]], time.monotonic()
    while window and now - window[0] > 60:
        window.popleft()
    if len(window) >= RATE_LIMIT:
        raise HTTPException(429, f"Limit is {RATE_LIMIT} questions a minute", headers={"Retry-After": "60"})
    window.append(now)
    return user


@app.post("/auth/token", response_model=Token, tags=["auth"])
def sign_in(body: TokenRequest) -> Token:
    return issue(check_password(body.password))


@app.post("/login", tags=["auth"], include_in_schema=False)
def sign_in_with_cookie(body: TokenRequest, request: Request, response: Response) -> dict:
    """Phone app sign-in: same token, kept in an HttpOnly cookie the page's scripts can't read."""
    token = issue(check_password(body.password), hours=24 * COOKIE_DAYS)
    # Secure (HTTPS-only) when the request came over HTTPS, e.g. via Tailscale Serve; plain on http://localhost
    https = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
    response.set_cookie(COOKIE, token.access_token, max_age=COOKIE_DAYS * 86400, httponly=True, samesite="strict",
                        secure=https)
    return {"role": token.role}


@app.get("/session", tags=["auth"], include_in_schema=False)
def session(user: dict = Depends(current_user)) -> dict:
    return {"role": user["role"]}


# ---------- network allowlist and request logging ----------

@app.middleware("http")
async def allowed_networks_only(request: Request, call_next):
    if ALLOWED_NETWORKS:
        try:
            address = ipaddress.ip_address((request.client.host if request.client else "").removeprefix("::ffff:"))
            allowed = any(address in network for network in ALLOWED_NETWORKS)
        except ValueError:
            allowed = False  # not a recognisable IP address: refuse rather than guess
        if not allowed:
            return JSONResponse({"detail": "Not allowed from this network."}, status_code=403)
    response = await call_next(request)
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    entry = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "method": request.method,
             "path": request.url.path, "status": response.status_code,
             "latency_ms": round(1000 * (time.perf_counter() - start)), **getattr(request.state, "usage", {})}
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as f:
        f.write(json.dumps(entry) + "\n")
    return response


# ---------- tools ----------

class Question(BaseModel):
    question: str = Field(min_length=3, max_length=500)


class Citation(BaseModel):
    citation: str
    content: str
    score: float


class SearchResponse(BaseModel):
    hits: list[Citation]


class SQLRequest(BaseModel):
    sql: str = Field(max_length=5000)


class SQLResponse(BaseModel):
    sql: str
    columns: list[str]
    rows: list[list]
    error: str | None = None


class SQLAnswer(BaseModel):
    answer: str
    sql: str
    columns: list[str]
    rows: list[list]
    attempts: int
    latency_s: float
    model_tokens: dict


@app.get("/health", tags=["system"])
def health() -> dict:
    checks = {}
    try:
        checks["database"] = run("SELECT count(*) FROM daily_sales").error is None
    except Exception:  # noqa: BLE001 - health must never raise
        checks["database"] = False
    return {"ok": all(checks.values()), **checks}


@app.post("/search", response_model=SearchResponse, tags=["copilot"])
def search_documents(body: Question, user: dict = Depends(current_user)) -> SearchResponse:
    """Menu and policy search (pgvector + BM25) with source citations."""
    return SearchResponse(hits=[Citation(citation=h.citation, content=h.content, score=h.score)
                                for h in search(body.question)])


@app.post("/sql", response_model=SQLResponse, tags=["copilot"])
def run_sql(body: SQLRequest, user: dict = Depends(owner_only)) -> SQLResponse:
    """Run a validated, read-only query directly (owners only)."""
    result = run(body.sql)
    return SQLResponse(sql=result.sql, columns=result.columns, rows=[list(r) for r in result.rows], error=result.error)


@app.post("/ask/sql", response_model=SQLAnswer, tags=["copilot"])
def ask_sql(body: Question, request: Request, user: dict = Depends(rate_limited)) -> SQLAnswer:
    """Answer a question about sales, orders or deliveries with Text-to-SQL."""
    answer = ask(body.question)
    request.state.usage = {"user": user["sub"], "input_tokens": answer.input_tokens,
                           "output_tokens": answer.output_tokens, "attempts": answer.attempts}
    result = answer.result
    return SQLAnswer(answer=answer.answer, sql=answer.sql, columns=result.columns if result else [],
                     rows=[list(r) for r in result.rows] if result and not result.error else [],
                     attempts=answer.attempts, latency_s=answer.latency_s,
                     model_tokens={"input": answer.input_tokens, "output": answer.output_tokens})


# ---------- phone app ----------

_retriever: dict = {}


def retriever() -> chatbot.Retriever:
    """Built on first use (it embeds the knowledge base), then reused."""
    if "r" not in _retriever:
        _retriever["r"] = chatbot.Retriever(chatbot.build_knowledge())
    return _retriever["r"]


class QueueWriter:
    """chatbot.answer() writes its reply here as it streams; the response generator reads it out."""

    def __init__(self, q: queue.Queue):
        self.q = q

    def write(self, text: str) -> None:
        self.q.put(text)

    def flush(self) -> None:
        pass


@app.post("/chat", tags=["copilot"])
def chat(body: Question, user: dict = Depends(rate_limited)) -> StreamingResponse:
    """The phone app's assistant: retrieval-augmented answers from the reports, streamed as they're written."""
    history = chat_histories.setdefault(user.get("sid", user["sub"]), [])
    pieces: queue.Queue = queue.Queue()
    done = object()

    def work():
        try:
            with model_lock:
                chatbot.answer(body.question, retriever(), history, stream_to=QueueWriter(pieces))
        except Exception as err:  # noqa: BLE001 - e.g. Ollama not running; tell the user instead of hanging
            pieces.put(f"\n[Error: {err}]")
        finally:
            pieces.put(done)

    threading.Thread(target=work, daemon=True).start()

    def stream():
        while (piece := pieces.get()) is not done:
            yield piece

    return StreamingResponse(stream(), media_type="text/plain; charset=utf-8", headers={"Cache-Control": "no-store"})


MANIFEST = {"name": "Grill House Assistant", "short_name": "Grill House", "start_url": "/", "scope": "/",
            "display": "standalone", "background_color": "#f6f5f2", "theme_color": "#c2410c",
            "icons": [{"src": "/static/icon-192.png", "sizes": "192x192", "type": "image/png"},
                      {"src": "/static/icon-512.png", "sizes": "512x512", "type": "image/png"},
                      {"src": "/static/icon-maskable-512.png", "sizes": "512x512", "type": "image/png",
                       "purpose": "maskable"}]}


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(UI / "index.html", headers={"Cache-Control": "no-cache"})


@app.get("/manifest.webmanifest", include_in_schema=False)
def manifest() -> JSONResponse:
    return JSONResponse(MANIFEST, media_type="application/manifest+json")


@app.get("/sw.js", include_in_schema=False)
def service_worker() -> Response:
    # Answers need the server, so the service worker only makes the page installable; it never caches
    return Response("self.addEventListener('fetch', () => {});", media_type="text/javascript",
                    headers={"Cache-Control": "no-cache"})


@app.get("/static/{name}", include_in_schema=False)
def static_file(name: str) -> FileResponse:
    path = (UI / name).resolve()
    if path.parent != UI or path.suffix != ".png" or not path.exists():
        raise HTTPException(404, "Not found")
    return FileResponse(path, headers={"Cache-Control": "max-age=86400"})
