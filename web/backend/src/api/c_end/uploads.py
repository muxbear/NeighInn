from __future__ import annotations

from fastapi import APIRouter

from src.core.deps import CurrentUser, DbSession
from src.core.responses import not_implemented

router = APIRouter(tags=["c:uploads"])

# 上传流水线（SRS 9.2/NF-06）：预签名 PUT → 上传确认（类型/大小/魔数双重校验）
# → 私有桶短时效签名 URL 访问。认证材料、纠纷证据一律私有桶。


@router.post("/uploads/presign")
async def presign_upload(user: CurrentUser, db: DbSession):
    raise not_implemented("POST /uploads/presign")


@router.post("/uploads/complete")
async def complete_upload(user: CurrentUser, db: DbSession):
    raise not_implemented("POST /uploads/complete")


@router.get("/uploads/{file_id}/url")
async def signed_url(file_id: int, user: CurrentUser, db: DbSession):
    raise not_implemented("GET /uploads/{id}/url")
