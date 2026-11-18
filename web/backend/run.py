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
        # uvicorn >= 0.54 在 Windows 上默认显式使用 ProactorEventLoop，会覆盖上面的
        # 事件循环策略设置，导致 psycopg 异步驱动报 InterfaceError。此处显式指定
        # SelectorEventLoop；其他平台保持 auto（Linux 下可继续使用 uvloop）。
        loop="asyncio:SelectorEventLoop" if sys.platform == "win32" else "auto",
        # 仅开发环境启用热重载；生产容器（APP_ENV=prod）直接运行，避免 reload 进程。
        reload=settings.app_env == "dev",
        reload_dirs=["src"],
        # 日志统一由 src/main.py 在导入时初始化；关闭 uvicorn 自带 logging config 与 access log，
        # 避免重复 handler 和两条访问日志。
        log_config=None,
        access_log=False,
    )
