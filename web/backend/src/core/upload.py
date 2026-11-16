"""上传文件类型与大小约束（C 端与管理端共用）。

只信任文件头识别结果，不信任客户端 multipart 声明的 Content-Type（NF-06）。
"""

from __future__ import annotations

MAX_IMAGE_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_VIDEO_UPLOAD_BYTES = 100 * 1024 * 1024
IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}
VIDEO_TYPES = {"video/mp4", "video/quicktime", "video/webm"}
EXT_BY_TYPE = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "application/pdf": ".pdf",
    "video/mp4": ".mp4",
    "video/quicktime": ".mov",
    "video/webm": ".webm",
}


def detect_content_type(head: bytes) -> str:
    """按文件头识别类型；无法识别时返回空串。"""
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    if head.startswith(b"%PDF-"):
        return "application/pdf"
    # ISO BMFF（mp4/mov）：ftyp box 通常位于文件头 4–8 字节；
    # 少数文件前面有 free/skip box，在前 32 字节内探测即可。
    ftyp_at = head[:32].find(b"ftyp")
    if ftyp_at >= 0 and len(head) >= ftyp_at + 8:
        brand = head[ftyp_at + 4:ftyp_at + 8]
        return "video/quicktime" if brand in {b"qt  ", b"qt"} else "video/mp4"
    # WebM/Matroska EBML 头。
    if head.startswith(b"\x1a\x45\xdf\xa3"):
        return "video/webm"
    return ""
