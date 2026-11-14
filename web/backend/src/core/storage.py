from __future__ import annotations

from datetime import timedelta
from functools import lru_cache
from pathlib import Path
from uuid import uuid4

from minio import Minio

from src.core.config import settings


@lru_cache(maxsize=1)
def get_minio() -> Minio:
    return Minio(
        settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=settings.minio_secure,
        region=settings.minio_region or None,
    )


def extension(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    return suffix if suffix in {".jpg", ".jpeg", ".png", ".webp", ".pdf", ".mp4", ".xlsx", ".csv"} else ".bin"


def presign_upload(filename: str, scene: str, content_type: str) -> dict:
    bucket = settings.minio_bucket_private
    if scene in {"PUBLIC_IMAGE", "COVER"}:
        bucket = settings.minio_bucket_public
    object_key = f"dev/{scene.lower()}/{uuid4().hex}{extension(filename)}"
    url = get_minio().presigned_put_object(
        bucket, object_key, expires=timedelta(minutes=15)
    )
    return {
        "bucket": bucket,
        "objectKey": object_key,
        "uploadUrl": url,
        "expiresAt": int((__import__("time").time() + 900) * 1000),
        "contentType": content_type,
    }


def presign_download(bucket: str, object_key: str) -> str:
    return get_minio().presigned_get_object(bucket, object_key, expires=timedelta(minutes=10))
