from __future__ import annotations

import logging
from datetime import timedelta
from functools import lru_cache
from pathlib import Path
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
    return suffix if suffix in {".jpg", ".jpeg", ".png", ".webp", ".pdf", ".mp4", ".xlsx", ".csv"} else ".bin"


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
