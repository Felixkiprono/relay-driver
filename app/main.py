from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.health import router as health_router
from app.api.routes import router as routes_router
from app.core.database import init_db
from app.core.logger import get_logger
from app.version import __version__

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    init_db()
    logger.info("Relay started")
    yield


app = FastAPI(title="Relay", version=__version__, lifespan=lifespan)
app.include_router(health_router)
app.include_router(routes_router)
