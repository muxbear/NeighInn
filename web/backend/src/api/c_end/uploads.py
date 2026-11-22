from __future__ import annotations

import hashlib
import io
import logging
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, File, Form, Response, UploadFile
from minio.error import S3Error
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool

from src.core.config import settings
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
from src.core.upload import (
    EXT_BY_TYPE,
    IMAGE_TYPES,
    MAX_IMAGE_UPLOAD_BYTES,
    MAX_VIDEO_UPLOAD_BYTES,
    VIDEO_TYPES,
    detect_content_type,
)
from src.db.models import FileObject

router = APIRouter(tags=["c:uploads"])
logger = logging.getLogger(__name__)

# 认证材料、纠纷证据一律私有桶；公开图片/生活短视频可走公共桶。
SCENE_TYPES: dict[str, tuple[set[str], str]] = {
    "REALNAME_ID": (IMAGE_TYPES, "private"),
    "OWNER_PROOF": (IMAGE_TYPES | {"application/pdf"}, "private"),
    "ITEM_IMAGE": (IMAGE_TYPES, "public"),
    "PUBLIC_IMAGE": (IMAGE_TYPES, "public"),
    "LIFE_VIDEO": (VIDEO_TYPES, "public"),
}


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
    max_bytes = MAX_VIDEO_UPLOAD_BYTES if allowed == VIDEO_TYPES else MAX_IMAGE_UPLOAD_BYTES
    if len(content) > max_bytes:
        limit_mb = max_bytes // (1024 * 1024)
        raise ApiError(ERR_FILE_TOO_LARGE, f"单个文件不能超过 {limit_mb}MB", 413)

    detected = detect_content_type(content[:16])
    if detected not in allowed:
        if allowed == VIDEO_TYPES:
            message = "仅支持 MP4 / MOV / WebM 短视频"
        elif "application/pdf" in allowed:
            message = "仅支持 JPG / PNG / WebP 图片或 PDF 文件"
        else:
            message = "仅支持 JPG / PNG / WebP 图片"
        raise ApiError(ERR_PARAM, message, 400)
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


# ---------------------------------------------------------------- 公开媒体同源代理

# 公开桶对象键只允许这些前缀；认证材料在私有桶，永不从这里出。
PUBLIC_MEDIA_PREFIXES = ("uploads/",)
_PUBLIC_MEDIA_MIME = {
    "jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
    "webp": "image/webp", "gif": "image/gif", "mp4": "video/mp4",
    "mov": "video/quicktime", "webm": "video/webm",
}


@router.get("/media/{object_key:path}")
async def public_media(object_key: str, db: DbSession):
    """公开媒体（物品图/生活动态）同源代理。

    签名 URL 以 ``MINIO_ENDPOINT`` 为主机，H5/管理端换机器访问时无法解析
    ``127.0.0.1:5206`` 这类内部地址；公开图改由后端读流返回，客户端只访问
    当前页面的同源 /api 路径。
    """
    key = object_key.lstrip("/")
    segments = key.split("/")
    if not key.startswith(PUBLIC_MEDIA_PREFIXES) or any(
            part in ("", ".", "..") for part in segments):
        raise ApiError(ERR_NOT_FOUND, "文件不存在", 404)

    record = await db.scalar(
        select(FileObject).where(FileObject.object_key == key))
    if record is not None and record.visibility != "public":
        raise ApiError(ERR_NOT_FOUND, "文件不存在", 404)

    client = get_minio()
    if client is None:
        raise ApiError(ERR_DEPENDENCY, "对象存储未配置，暂无法访问文件", 503)
    upstream = None
    try:
        upstream = await run_in_threadpool(
            client.get_object, settings.minio_bucket_public, key)
        data = await run_in_threadpool(upstream.read)
    except S3Error as exc:
        logger.warning("公开媒体不存在 %s：%s", key, exc)
        raise ApiError(ERR_NOT_FOUND, "文件不存在", 404) from exc
    except Exception as exc:  # 网络/连接异常降级为依赖不可用
        logger.warning("公开媒体读取异常 %s：%s", key, exc)
        raise ApiError(ERR_DEPENDENCY, "文件读取失败，请稍后重试", 503) from exc
    finally:
        if upstream is not None:
            await run_in_threadpool(upstream.close)
            await run_in_threadpool(upstream.release_conn)

    media_type = (record.content_type if record and record.content_type else "") or \
        _PUBLIC_MEDIA_MIME.get(key.rsplit(".", 1)[-1].lower(), "application/octet-stream")
    # 键名含 uuid，内容不会变，可长缓存。
    return Response(content=data, media_type=media_type, headers={
        "Cache-Control": "public, max-age=604800",
        "Content-Disposition": "inline",
    })
