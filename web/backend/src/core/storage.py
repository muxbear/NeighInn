from __future__ import annotations

import hashlib
import hmac
import logging
import time
from datetime import timedelta
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote
from uuid import uuid4

from minio import Minio
from minio.error import S3Error
from urllib3.exceptions import HTTPError as Urllib3Error

from src.core.config import settings

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_minio() -> Minio | None:
    try:
        return Minio(
            settings.minio_endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            secure=settings.minio_secure,
            # 显式 region：避免 SDK 为签名联网探测 bucket 位置（离线环境直连失败）
            region=settings.minio_region or "us-east-1",
        )
    except (ValueError, TypeError) as exc:  # pragma: no cover
        logger.warning("MinIO 初始化失败，文件能力降级：%s", exc)
        return None


def extension(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    return suffix if suffix in {".jpg", ".jpeg", ".png", ".webp", ".pdf", ".mp4",
                                ".mov", ".webm", ".xlsx", ".csv"} else ".bin"


def presign_upload(filename: str, scene: str, content_type: str) -> dict | None:
    client = get_minio()
    if client is None:
        return None
    bucket = settings.minio_bucket_private
    if scene in {"PUBLIC_IMAGE", "COVER"}:
        bucket = settings.minio_bucket_public
    object_key = f"uploads/{scene.lower()}/{uuid4().hex}{extension(filename)}"
    url = client.presigned_put_object(bucket, object_key, expires=timedelta(minutes=15))
    return {"bucket": bucket, "objectKey": object_key, "uploadUrl": url,
            "expiresAt": 15 * 60, "contentType": content_type}


def presign_download(object_key: str, bucket: str | None = None, minutes: int = 10) -> str | None:
    """私有桶短时效签名 URL（SRS 9.2：认证材料 10 分钟）。"""
    client = get_minio()
    if client is None:
        return None
    try:
        return client.presigned_get_object(
            bucket or settings.minio_bucket_private, object_key,
            expires=timedelta(minutes=minutes),
        )
    except (S3Error, Urllib3Error, OSError, ValueError) as exc:
        logger.warning("签名 URL 生成失败（对象可能不存在或服务不可用）：%s", exc)
        return None


PUBLIC_MEDIA_URL_TTL_MINUTES = 60 * 24 * 7


def public_media_url(object_key: str | None) -> str:
    """对象键 → 客户端可直接加载的公开媒体地址。

    公开桶同样走统一服务端的同源代理（``/api/v1/media/<key>``）：签名 URL 以
    ``MINIO_ENDPOINT`` 为主机，H5/管理端在别的机器上访问时无法解析
    ``127.0.0.1:5206`` 之类的内部地址，图片必然加载失败。
    """
    key = str(object_key or "").strip()
    if not key:
        return ""
    if key.startswith(("http://", "https://", "data:", "blob:")):
        return key
    base = (settings.public_media_base_url or "").rstrip("/")
    return f"{base}/api/v1/media/{quote(key, safe='/')}"


# ---------------------------------------------------------------- 私信媒体（私有桶）

# 私信图片/视频存放在私有桶；客户端通过带 HMAC 签名的同源地址访问，
# 避免把 MinIO 内网地址暴露给手机浏览器（签名 URL 主机常为 127.0.0.1:5206）。
CHAT_MEDIA_PREFIX = "chat/"
CHAT_MEDIA_URL_TTL_SECONDS = 7 * 24 * 3600


def _chat_media_signature(object_key: str, expires_at: int) -> str:
    message = f"chat-media:{object_key}:{expires_at}".encode()
    return hmac.new(
        settings.secret_key.encode(), message, hashlib.sha256
    ).hexdigest()


def private_media_url(
    object_key: str | None, ttl_seconds: int = CHAT_MEDIA_URL_TTL_SECONDS
) -> str:
    """私信媒体对象键 → 带时效签名的同源访问地址。"""
    key = str(object_key or "").strip()
    if not key:
        return ""
    if key.startswith(("http://", "https://", "data:", "blob:")):
        return key
    if not key.startswith(CHAT_MEDIA_PREFIX):
        # 只对私信媒体签名；认证材料等私有文件不得走此通道。
        return ""
    expires_at = int(time.time()) + max(60, ttl_seconds)
    signature = _chat_media_signature(key, expires_at)
    base = (settings.public_media_base_url or "").rstrip("/")
    return (
        f"{base}/api/v1/media/private/{quote(key, safe='/')}"
        f"?e={expires_at}&s={signature}"
    )


def verify_private_media_signature(
    object_key: str, expires_at: int, signature: str
) -> bool:
    """校验私信媒体签名（constant-time）；仅接受 chat/ 前缀。"""
    key = str(object_key or "").lstrip("/")
    if not key.startswith(CHAT_MEDIA_PREFIX):
        return False
    if expires_at < int(time.time()):
        return False
    expected = _chat_media_signature(key, expires_at)
    return hmac.compare_digest(expected, str(signature or ""))
