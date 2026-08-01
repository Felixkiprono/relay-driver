from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.services import health as health_service
from app.version import __version__

router = APIRouter()


@router.get("/health")
def health(db: Session = Depends(get_db)) -> dict:
    return health_service.check(db)


@router.get("/version")
def version() -> dict:
    return {"version": __version__}
