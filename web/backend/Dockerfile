# syntax=docker/dockerfile:1.7
# 邻里小栈统一服务端（FastAPI）生产镜像。
# 构建：docker build -t neighinn-backend ./web/backend
# 运行：docker run --rm --network host --env-file web/backend/.env.prod neighinn-backend
FROM python:3.12-slim AS runtime

# uv：按 uv.lock 安装依赖，保证与本地开发一致。
# 如需完全可复现构建，可将 latest 固定为与 uv.lock 兼容的具体版本。
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# 先安装依赖，利用 Docker 层缓存；项目本身不打包（pyproject 中 package = false）。
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# 应用代码与迁移脚本。
COPY alembic.ini ./
COPY alembic ./alembic
COPY src ./src
COPY run.py ./
COPY docker-entrypoint.sh ./

# 容器内使用非 root 用户运行；Windows 检出可能带 CRLF，统一转为 LF。
RUN sed -i 's/\r$//' /app/docker-entrypoint.sh \
    && chmod +x /app/docker-entrypoint.sh \
    && groupadd --gid 10001 app \
    && useradd --create-home --uid 10001 --gid app app \
    && chown -R app:app /app

USER app

EXPOSE 5193

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/health/live' % os.getenv('APP_PORT', '5193'), timeout=3)" || exit 1

ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["python", "run.py"]
