from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from src.core.deps import CurrentUser, DbSession
from src.core.responses import not_implemented, ok
from src.services import auth_service as svc

router = APIRouter(tags=["c:users"])


class ProfileIn(BaseModel):
    nickname: str | None = None
    email: str | None = None
    address: str | None = None
    bio: str | None = None
    showBio: bool | None = None
    shareAddressAfterOrder: bool | None = None


@router.get("/users/me")
async def get_profile(user: CurrentUser, db: DbSession):
    return ok(await svc.serialize_profile(db, user))


@router.put("/users/me")
async def update_profile(payload: ProfileIn, user: CurrentUser, db: DbSession):
    if payload.nickname:
        user.nickname = payload.nickname[:24]
    await db.commit()
    return ok(await svc.serialize_profile(db, user), "资料已更新")


@router.post("/users/me/avatar")
async def update_avatar(user: CurrentUser, db: DbSession):
    raise not_implemented("POST /users/me/avatar（头像库，Phase 2）")
