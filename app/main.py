from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.v1 import router as v1_router
from app.core import __version__, get_logger
from app.database import init_db

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    init_db()
    logger.info("Relay started")
    yield


app = FastAPI(title="Relay", version=__version__, lifespan=lifespan)
app.include_router(v1_router)
