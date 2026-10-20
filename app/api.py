"""Copilot backend: authentication, rate limits, request logging and the copilot's tools as HTTP endpoints.

Run from the project root:
    uvicorn app.api:app --port 8000          # docs at http://localhost:8000/docs

Sign in with POST /auth/token to get a bearer token; it carries a role (owner or staff) for role-based access.
"""

import hmac
import json
import os
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

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

app = FastAPI(title="Grill House Ops Copilot", version="0.2.0",
              description="AI analyst for a late-night takeaway: Text-to-SQL over sales and deliveries, cited menu "
                          "and policy search. Demo data is synthetic.")
bearer = HTTPBearer(auto_error=False)
recent_requests: dict[str, deque] = defaultdict(deque)


# ---------- auth ----------

class TokenRequest(BaseModel):
    password: str = Field(max_length=200)


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    expires_at: datetime


def issue(role: str) -> Token:
    expires = datetime.now(timezone.utc) + timedelta(hours=TOKEN_HOURS)
    token = jwt.encode({"sub": role, "role": role, "exp": expires}, JWT_SECRET, algorithm="HS256")
    return Token(access_token=token, role=role, expires_at=expires)


def current_user(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)) -> dict:
    if credentials is None:
        raise HTTPException(401, "Sign in at /auth/token first", headers={"WWW-Authenticate": "Bearer"})
    try:
        return jwt.decode(credentials.credentials, JWT_SECRET, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(401, "Invalid or expired token", headers={"WWW-Authenticate": "Bearer"}) from None


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
    if not JWT_SECRET:
        raise HTTPException(500, "Server not configured: set GRILLHOUSE_JWT_SECRET")
    for role, password in ROLE_PASSWORDS.items():
        if len(password) >= 8 and hmac.compare_digest(body.password.encode(), password.encode()):
            return issue(role)
    raise HTTPException(401, "Wrong password")


# ---------- request logging ----------

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
