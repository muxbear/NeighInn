from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from src.core.deps import CurrentAdmin
from src.core.responses import ok
from src.core.storage import presign_upload

router = APIRouter(prefix="/files", tags=["files"])


class PresignIn(BaseModel):
    filename: str
    contentType: str = "application/octet-stream"
    size: int = 0
    scene: str = "CERTIFICATION"


@router.post("/presign")
def presign(payload: PresignIn, admin: CurrentAdmin):
    data = presign_upload(payload.filename, payload.scene, payload.contentType)
    return ok(data, "预签名地址已生成")
