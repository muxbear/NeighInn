from __future__ import annotations

import hashlib
import io
import logging
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, UploadFile
from starlette.concurrency import run_in_threadpool

from src.core.config import settings
from src.core.deps import CurrentAdmin, DbSession
from src.core.permissions import require_permission
from src.core.responses import (
    ERR_DEPENDENCY,
    ERR_FILE_TOO_LARGE,
    ERR_PARAM,
    ApiError,
    not_implemented,
    ok,
)
from src.core.storage import extension, get_minio, public_media_url
from src.core.upload import (
    EXT_BY_TYPE,
    IMAGE_TYPES,
    MAX_IMAGE_UPLOAD_BYTES,
    MAX_VIDEO_UPLOAD_BYTES,
    VIDEO_TYPES,
    detect_content_type,
)
from src.db.models import FileObject

router = APIRouter(tags=["admin:files"])
logger = logging.getLogger(__name__)

# 文件流水线：预签名（15 分钟 PUT）→ 上传确认（类型/大小/魔数校验）
# → 私有桶签名下载（10 分钟，查看原图写审计）。

# 管理端只开放公开媒体（生活内容配图/短视频），认证材料仍走 C 端私有通道。
ADMIN_MEDIA_SCENES: dict[str, set[str]] = {
    "PUBLIC_IMAGE": IMAGE_TYPES,
    "LIFE_IMAGE": IMAGE_TYPES,
    "LIFE_VIDEO": VIDEO_TYPES,
}


@router.post("/files/upload",
             dependencies=[Depends(require_permission("community:life:update"))])
async def upload_public_media(
    admin: CurrentAdmin,
    db: DbSession,
    file: Annotated[UploadFile, File()],
    scene: Annotated[str, Form()] = "LIFE_IMAGE",
):
    """管理端 multipart 上传生活内容媒体（公开桶），返回对象键与可访问 URL。"""
    allowed = ADMIN_MEDIA_SCENES.get(scene)
    if not allowed:
        raise ApiError(ERR_PARAM, "不支持的上传场景", 400)

    content = await file.read()
    if not content:
        raise ApiError(ERR_PARAM, "上传文件为空", 400)
    max_bytes = MAX_VIDEO_UPLOAD_BYTES if allowed == VIDEO_TYPES else MAX_IMAGE_UPLOAD_BYTES
    if len(content) > max_bytes:
        limit_mb = max_bytes // (1024 * 1024)
        raise ApiError(ERR_FILE_TOO_LARGE, f"单个文件不能超过 {limit_mb}MB", 413)

    detected = detect_content_type(content[:16])
    if detected not in allowed:
        message = ("仅支持 MP4 / MOV / WebM 短视频" if allowed == VIDEO_TYPES
                   else "仅支持 JPG / PNG / WebP 图片")
        raise ApiError(ERR_PARAM, message, 400)

    original_name = file.filename or f"upload{EXT_BY_TYPE.get(detected, extension(''))}"
    suffix = EXT_BY_TYPE.get(detected) or extension(original_name)
    object_key = f"uploads/{scene.lower()}/{admin.id}/{uuid4().hex}{suffix}"

    client = get_minio()
    if client is None:
        raise ApiError(ERR_DEPENDENCY, "对象存储未配置，暂无法上传媒体", 503)
    bucket = settings.minio_bucket_public
    try:
        if hasattr(client, "bucket_exists"):
            exists = await run_in_threadpool(client.bucket_exists, bucket)
            if not exists:
                await run_in_threadpool(client.make_bucket, bucket)
        await run_in_threadpool(
            client.put_object,
            bucket,
            object_key,
            io.BytesIO(content),
            len(content),
            content_type=detected,
        )
    except Exception as exc:  # 对象存储异常统一转依赖不可用
        logger.warning("管理端媒体上传失败：%s", exc)
        raise ApiError(ERR_DEPENDENCY, "媒体上传失败，请稍后重试", 503) from exc

    record = FileObject(
        bucket=bucket,
        object_key=object_key,
        original_name=original_name,
        content_type=detected,
        size_bytes=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
        visibility="public",
        uploaded_by=admin.id,
    )
    db.add(record)
    await db.commit()
    return ok({
        "fileId": str(record.id),
        "objectKey": object_key,
        "url": public_media_url(object_key),
        "contentType": detected,
        "sizeBytes": len(content),
    }, "上传成功")


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
