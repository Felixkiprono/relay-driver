from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.drivers.manager import get_driver_manager
from app.services import network

router = APIRouter()


class CreateUserRequest(BaseModel):
    username: str
    password: str


class DeleteUserRequest(BaseModel):
    username: str


class ActivatePackageRequest(BaseModel):
    username: str
    package: str


class DisconnectUserRequest(BaseModel):
    username: str


class CreateVoucherRequest(BaseModel):
    package: str


@router.get("/drivers")
def drivers() -> dict:
    return {"active": settings.driver}


@router.get("/online")
def online() -> list:
    return get_driver_manager().dispatch("online_users")


@router.get("/statistics")
def statistics() -> dict:
    return get_driver_manager().dispatch("statistics")


@router.post("/user/create")
def create_user(body: CreateUserRequest, db: Session = Depends(get_db)) -> dict:
    return network.execute(db, "create_user", username=body.username, password=body.password)


@router.post("/user/delete")
def delete_user(body: DeleteUserRequest, db: Session = Depends(get_db)) -> dict:
    return network.execute(db, "delete_user", username=body.username)


@router.post("/package/activate")
def activate_package(body: ActivatePackageRequest, db: Session = Depends(get_db)) -> dict:
    return network.execute(db, "activate_package", username=body.username, package=body.package)


@router.post("/user/disconnect")
def disconnect_user(body: DisconnectUserRequest, db: Session = Depends(get_db)) -> dict:
    return network.execute(db, "disconnect_user", username=body.username)


@router.post("/voucher/create")
def create_voucher(body: CreateVoucherRequest, db: Session = Depends(get_db)) -> dict:
    return network.execute(db, "create_voucher", package=body.package)
