from __future__ import annotations

import hashlib
import io
import logging
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, File, Form, UploadFile
from starlette.concurrency import run_in_threadpool

from src.core.deps import CurrentUser, DbSession
from src.core.responses import (
    ERR_DEPENDENCY,
    ERR_FILE_TOO_LARGE,
    ERR_NOT_FOUND,
    ERR_PARAM,
    ApiError,
    ok,
)
from src.core.storage import extension, get_minio, presign_download
from src.db.models import FileObject

router = APIRouter(tags=["c:uploads"])
logger = logging.getLogger(__name__)

# 认证材料、纠纷证据一律私有桶；公开图片可走公共桶。
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}
SCENE_TYPES: dict[str, tuple[set[str], str]] = {
    "REALNAME_ID": (IMAGE_TYPES, "private"),
    "OWNER_PROOF": (IMAGE_TYPES | {"application/pdf"}, "private"),
    "ITEM_IMAGE": (IMAGE_TYPES, "public"),
    "PUBLIC_IMAGE": (IMAGE_TYPES, "public"),
}
EXT_BY_TYPE = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "application/pdf": ".pdf",
}


def _detect_content_type(head: bytes) -> str:
    """按文件头识别类型，不能只信任客户端 Content-Type（NF-06）。"""
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    if head.startswith(b"%PDF-"):
        return "application/pdf"
    return ""


@router.post("/uploads")
async def upload_file(
    user: CurrentUser,
    db: DbSession,
    file: Annotated[UploadFile, File()],
    scene: Annotated[str, Form()] = "PUBLIC_IMAGE",
):
    """移动端 multipart 直传（uni.uploadFile 不支持预签名 PUT）。

    认证材料写入 ni-private，返回对象键；前端提交认证时只传对象键。
    """
    allowed, visibility = SCENE_TYPES.get(scene, (set(), ""))
    if not allowed:
        raise ApiError(ERR_PARAM, "不支持的上传场景", 400)

    content = await file.read()
    if not content:
        raise ApiError(ERR_PARAM, "上传文件为空", 400)
    if len(content) > MAX_UPLOAD_BYTES:
        raise ApiError(ERR_FILE_TOO_LARGE, "单个文件不能超过 10MB", 413)

    detected = _detect_content_type(content[:16])
    if detected not in allowed:
        raise ApiError(ERR_PARAM, "仅支持 JPG / PNG / WebP 图片" if "application/pdf" not in allowed
                       else "仅支持 JPG / PNG / WebP 图片或 PDF 文件", 400)
    # 以文件头识别结果为准；不信任客户端 multipart 声明的 Content-Type，
    # 避免 App/小程序端把图片统一标成 octet-stream 时误拒。
    original_name = file.filename or f"upload{EXT_BY_TYPE.get(detected, extension(''))}"
    suffix = EXT_BY_TYPE.get(detected) or extension(original_name)
    prefix = "certifications" if visibility == "private" else "uploads"
    object_key = f"{prefix}/{scene.lower()}/{user.id}/{uuid4().hex}{suffix}"

    client = get_minio()
    if client is None:
        raise ApiError(ERR_DEPENDENCY, "对象存储未配置，暂无法上传材料", 503)
    bucket = settings_bucket(visibility)
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
        logger.warning("上传对象存储失败：%s", exc)
        raise ApiError(ERR_DEPENDENCY, "材料上传失败，请稍后重试", 503) from exc

    record = FileObject(
        bucket=bucket,
        object_key=object_key,
        original_name=original_name,
        content_type=detected,
        size_bytes=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
        visibility=visibility,
        uploaded_by=user.id,
    )
    db.add(record)
    await db.commit()
    return ok({
        "fileId": str(record.id),
        "objectKey": object_key,
        "bucket": bucket,
        "visibility": visibility,
        "contentType": detected,
        "sizeBytes": len(content),
    }, "上传成功")


def settings_bucket(visibility: str) -> str:
    from src.core.config import settings

    return settings.minio_bucket_public if visibility == "public" else settings.minio_bucket_private


@router.get("/uploads/{file_id}/url")
async def signed_url(file_id: int, user: CurrentUser, db: DbSession):
    record = await db.get(FileObject, file_id)
    if not record or record.uploaded_by != user.id:
        raise ApiError(ERR_NOT_FOUND, "文件不存在", 404)
    url = presign_download(record.object_key, record.bucket, minutes=10)
    if not url:
        raise ApiError(ERR_DEPENDENCY, "对象存储不可用，暂无法访问文件", 503)
    return ok({"signedUrl": url, "expiresIn": 600})


# 预签名上传保留给后续 Web 端/大文件场景；移动端认证材料不走此通道。
@router.post("/uploads/presign")
async def presign_upload(user: CurrentUser, db: DbSession):
    from src.core.responses import not_implemented

    raise not_implemented("POST /uploads/presign")


@router.post("/uploads/complete")
async def complete_upload(user: CurrentUser, db: DbSession):
    from src.core.responses import not_implemented

    raise not_implemented("POST /uploads/complete")
