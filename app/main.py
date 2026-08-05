import json
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response

from app.api.v1 import public_router, router as v1_router
from app.core import __version__, get_logger
from app.database import init_db

logger = get_logger(__name__)

REDACTED_FIELDS = {"password"}


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    init_db()
    logger.info("Relay started")
    yield


app = FastAPI(
    title="Relay",
    description=(
        "A lightweight network access service. Relay receives requests from "
        "business systems (e.g. Laravel), executes them against the configured "
        "network driver (e.g. daloRADIUS), and returns the result.\n\n"
        "Every endpoint except `/api/v1/health` requires an `X-API-KEY` header "
        "— click **Authorize** below to set it once for all requests on this page."
    ),
    version=__version__,
    lifespan=lifespan,
)


def _redact(payload: object) -> object:
    if isinstance(payload, dict):
        return {key: ("[redacted]" if key in REDACTED_FIELDS else value) for key, value in payload.items()}
    return payload


@app.middleware("http")
async def log_requests(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
    start = time.monotonic()
    client = request.client.host if request.client else "-"

    body_preview = ""
    if request.method in {"POST", "PUT", "PATCH"}:
        raw_body = await request.body()
        if raw_body:
            try:
                body_preview = json.dumps(_redact(json.loads(raw_body)))
            except ValueError:
                body_preview = "<non-json body>"

    logger.info(
        "→ %s %s%s from=%s%s",
        request.method,
        request.url.path,
        f"?{request.url.query}" if request.url.query else "",
        client,
        f" body={body_preview}" if body_preview else "",
    )

    response = await call_next(request)
    duration_ms = int((time.monotonic() - start) * 1000)

    log = logger.warning if response.status_code >= 400 else logger.info
    log("← %s %s %s %dms", request.method, request.url.path, response.status_code, duration_ms)

    return response


app.include_router(public_router)
app.include_router(v1_router)
