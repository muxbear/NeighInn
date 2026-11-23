from __future__ import annotations

import hashlib
import io
import logging
from collections.abc import Iterator
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, File, Form, Request, Response, UploadFile
from minio.error import S3Error
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool
from starlette.responses import StreamingResponse

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
from src.core.storage import (
    extension,
    get_minio,
    presign_download,
    verify_private_media_signature,
)
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

# 认证材料、私信媒体一律私有桶；公开图片/生活短视频可走公共桶。
SCENE_TYPES: dict[str, tuple[set[str], str]] = {
    "REALNAME_ID": (IMAGE_TYPES, "private"),
    "OWNER_PROOF": (IMAGE_TYPES | {"application/pdf"}, "private"),
    "ITEM_IMAGE": (IMAGE_TYPES, "public"),
    "PUBLIC_IMAGE": (IMAGE_TYPES, "public"),
    "LIFE_VIDEO": (VIDEO_TYPES, "public"),
    "CHAT_IMAGE": (IMAGE_TYPES, "private"),
    "CHAT_VIDEO": (VIDEO_TYPES, "private"),
}

# 私信媒体与认证材料同桶不同前缀，便于签名通道只放行 chat/。
PRIVATE_SCENE_PREFIX = {
    "CHAT_IMAGE": "chat",
    "CHAT_VIDEO": "chat",
}

_MEDIA_MIME = {
    "jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
    "webp": "image/webp", "gif": "image/gif", "mp4": "video/mp4",
    "mov": "video/quicktime", "webm": "video/webm",
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
    if visibility == "private":
        prefix = PRIVATE_SCENE_PREFIX.get(scene, "certifications")
    else:
        prefix = "uploads"
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


# ---------------------------------------------------------------- 私信媒体同源代理

def _iter_minio_object(upstream) -> Iterator[bytes]:
    """同步分块迭代，Starlette 会在工作线程中消费，避免大视频阻塞事件循环。"""
    try:
        while True:
            chunk = upstream.read(64 * 1024)
            if not chunk:
                break
            yield chunk
    finally:
        upstream.close()
        upstream.release_conn()


def _parse_byte_range(range_header: str, total: int) -> tuple[int, int] | str | None:
    """解析单段 Range：返回 (start, end) 闭区间 / 'invalid' / None（无 Range）。

    浏览器播放 <video> 时会先发 ``Range: bytes=0-``，iOS/微信内核还依赖 206 +
    Content-Range 才能起播；不支持 Range 时表现为“视频加载失败/点了没反应”。
    """
    header = (range_header or "").strip()
    if not header.startswith("bytes="):
        return None
    spec = header[len("bytes="):].split(",", 1)[0].strip()
    if "-" not in spec:
        return "invalid"
    start_text, _, end_text = spec.partition("-")
    try:
        if not start_text:
            suffix = int(end_text)
            if suffix <= 0 or total <= 0:
                return "invalid"
            start, end = max(0, total - suffix), total - 1
        else:
            start = int(start_text)
            end = int(end_text) if end_text else total - 1
    except ValueError:
        return "invalid"
    if total <= 0 or start >= total or start > end:
        return "invalid"
    return start, min(end, total - 1)


async def _media_stream_response(
    request,
    client,
    *,
    bucket: str,
    key: str,
    media_type: str,
    cache_control: str,
) -> Response:
    """从对象存储流式返回媒体，支持 Range/HEAD（视频拖动与 iOS 起播必需）。"""
    try:
        stat = await run_in_threadpool(client.stat_object, bucket, key)
    except S3Error as exc:
        logger.warning("媒体不存在 %s：%s", key, exc)
        raise ApiError(ERR_NOT_FOUND, "文件不存在", 404) from exc
    except Exception as exc:
        logger.warning("媒体信息读取异常 %s：%s", key, exc)
        raise ApiError(ERR_DEPENDENCY, "文件读取失败，请稍后重试", 503) from exc

    total = int(getattr(stat, "size", 0) or 0)
    content_type = media_type or getattr(stat, "content_type", "") or "application/octet-stream"
    parsed = _parse_byte_range(request.headers.get("range", ""), total)
    headers = {
        "Accept-Ranges": "bytes",
        "Content-Disposition": "inline",
        "Cache-Control": cache_control,
    }
    if parsed == "invalid":
        headers["Content-Range"] = f"bytes */{total}"
        return Response(status_code=416, headers=headers, media_type=content_type)
    if total <= 0:
        headers["Content-Length"] = "0"
        return Response(status_code=200, content=b"", headers=headers, media_type=content_type)

    if parsed is None:
        start, end, status_code = 0, total - 1, 200
    else:
        start, end = parsed
        status_code = 206
        headers["Content-Range"] = f"bytes {start}-{end}/{total}"
    length = end - start + 1
    headers["Content-Length"] = str(length)

    try:
        upstream = await run_in_threadpool(
            client.get_object, bucket, key, offset=start, length=length)
    except S3Error as exc:
        logger.warning("媒体不存在 %s：%s", key, exc)
        raise ApiError(ERR_NOT_FOUND, "文件不存在", 404) from exc
    except Exception as exc:
        logger.warning("媒体读取异常 %s：%s", key, exc)
        raise ApiError(ERR_DEPENDENCY, "文件读取失败，请稍后重试", 503) from exc

    if request.method.upper() == "HEAD":
        await run_in_threadpool(upstream.close)
        await run_in_threadpool(upstream.release_conn)
        return Response(status_code=status_code, headers=headers, media_type=content_type)
    return StreamingResponse(
        _iter_minio_object(upstream),
        status_code=status_code,
        media_type=content_type,
        headers=headers,
    )


# 注意：必须注册在 /media/{object_key:path} 之前，否则会被公开媒体路由吞掉。
@router.head("/media/private/{object_key:path}")
@router.get("/media/private/{object_key:path}")
async def private_media(
    object_key: str, request: Request, db: DbSession, e: int = 0, s: str = ""
):
    """私信图片/短视频同源代理（私有桶 + HMAC 时效签名）。

    签名由 ``private_media_url`` 在消息下发时生成，只对 ``chat/`` 前缀有效；
    签名本身即访问凭证，因此不要求额外 Bearer Token（``<image>``/``<video>``
    无法携带请求头）。视频需支持 Range/206，浏览器才能起播和拖动进度。
    """
    key = object_key.lstrip("/")
    segments = key.split("/")
    if any(part in ("", ".", "..") for part in segments):
        raise ApiError(ERR_NOT_FOUND, "文件不存在", 404)
    if not verify_private_media_signature(key, e, s):
        raise ApiError(ERR_NOT_FOUND, "文件不存在", 404)

    record = await db.scalar(
        select(FileObject).where(FileObject.object_key == key))
    if record is not None and record.visibility != "private":
        raise ApiError(ERR_NOT_FOUND, "文件不存在", 404)

    client = get_minio()
    if client is None:
        raise ApiError(ERR_DEPENDENCY, "对象存储未配置，暂无法访问文件", 503)
    media_type = (record.content_type if record and record.content_type else "") or \
        _MEDIA_MIME.get(key.rsplit(".", 1)[-1].lower(), "application/octet-stream")
    return await _media_stream_response(
        request, client,
        bucket=settings.minio_bucket_private,
        key=key,
        media_type=media_type,
        cache_control="private, max-age=600",
    )


# ---------------------------------------------------------------- 公开媒体同源代理

# 公开桶对象键只允许这些前缀；认证材料与私信媒体在私有桶，永不从这里出。
PUBLIC_MEDIA_PREFIXES = ("uploads/",)


@router.head("/media/{object_key:path}")
@router.get("/media/{object_key:path}")
async def public_media(object_key: str, request: Request, db: DbSession):
    """公开媒体（物品图/生活动态）同源代理。

    签名 URL 以 ``MINIO_ENDPOINT`` 为主机，H5/管理端换机器访问时无法解析
    ``127.0.0.1:5206`` 这类内部地址；公开图改由后端读流返回，客户端只访问
    当前页面的同源 /api 路径。视频同样支持 Range/206。
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
    media_type = (record.content_type if record and record.content_type else "") or \
        _MEDIA_MIME.get(key.rsplit(".", 1)[-1].lower(), "application/octet-stream")
    # 键名含 uuid，内容不会变，可长缓存。
    return await _media_stream_response(
        request, client,
        bucket=settings.minio_bucket_public,
        key=key,
        media_type=media_type,
        cache_control="public, max-age=604800",
    )
