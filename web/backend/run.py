from __future__ import annotations

import asyncio
import sys

# Windows 下 psycopg 异步驱动不支持默认的 ProactorEventLoop，
# 必须切换为 SelectorEventLoop（与 web/backend/run.py 相同原因）。
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import uvicorn

from src.core.config import settings

if __name__ == "__main__":
    uvicorn.run(
        "src.main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=True,
        reload_dirs=["src"],
    )
