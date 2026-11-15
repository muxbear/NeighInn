from __future__ import annotations

from fastapi import APIRouter

from src.core.deps import CurrentAdmin, DbSession
from src.core.responses import not_implemented

router = APIRouter(tags=["admin:files"])

# 文件流水线：预签名（15 分钟 PUT）→ 上传确认（类型/大小/魔数校验）
# → 私有桶签名下载（10 分钟，查看原图写审计）。


@router.post("/files/presign")
async def presign(admin: CurrentAdmin, db: DbSession):
    raise not_implemented("POST /files/presign")


@router.post("/files/{file_id}/complete")
async def complete(file_id: int, admin: CurrentAdmin, db: DbSession):
    raise not_implemented("POST /files/{id}/complete")


@router.get("/files/{file_id}/url")
async def signed_url(file_id: int, admin: CurrentAdmin, db: DbSession):
    """私有文件签名 URL：敏感场景（认证材料/纠纷证据）每次查看写审计。"""
    raise not_implemented("GET /files/{id}/url")
