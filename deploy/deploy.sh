#!/usr/bin/env bash
# =============================================================================
# NeighInn 生产部署脚本
#
# 功能：
#   1. 每次运行都从 GitHub 拉取最新 main 分支代码（丢弃服务器上的代码改动）；
#   2. 构建指定组件的 Docker 镜像，并以 docker compose 部署到本机容器；
#   3. 等待容器健康检查通过，再执行烟雾测试（含数据库查询与 nginx 反代）。
#
# 用法：
#   ./deploy.sh backend     # 统一服务端（web/backend，端口 5193）
#   ./deploy.sh frontend    # Web 管理端（web/frontend，端口 5192）
#   ./deploy.sh mobile      # 移动端 H5（mobile，端口 80）
#   ./deploy.sh backend --no-cache   # 不使用 Docker 构建缓存
#
# 生产配置：
#   web/backend/.env.prod（已被 gitignore，代码更新不会覆盖或删除它）
#
# 移动端说明：
#   uni-app x 的 H5 产物只能由 HBuilderX 编译，Linux 服务器无法从源码构建。
#   请先在 HBuilderX 中将 mobile/config/env.ts 的 CURRENT_ENV 改为 'docker'，
#   发行到 Web，然后把产物放到以下任一目录，再运行本脚本：
#     /opt/soft/NeighInn/artifacts/mobile-h5
#     /opt/soft/NeighInn/mobile/unpackage/dist/build/web
#   也可用环境变量 MOBILE_H5_DIST=/path/to/dist 指定产物目录。
#
# 可选配置：
#   同目录 deploy.conf（不存在则跳过）可设置 PyPI 镜像，例如：
#     UV_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
#   后端构建时会把 uv.lock 中的 PyPI 下载地址改写到该镜像（不改仓库文件），
#   避免从 PyPI 直连下载过慢；uv 仍会校验 lock 中的文件 hash。
#
# 迁移兼容补丁：
#   上游 0001 迁移按最新模型 create_all，导致全新数据库上 0008/0009 重复加列。
#   脚本会在临时构建上下文中为这两个迁移加“列已存在则跳过”的判断（不改仓库），
#   上游修复后会自动跳过补丁。
# =============================================================================
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
BASE_DIR="$(cd -- "${SCRIPT_DIR}/.." && pwd)"

REPO_URL="git@github.com:muxbear/NeighInn.git"
BRANCH="main"

# 兼容两种布局：
#   A（当前）：deploy/ 位于仓库内部 → 仓库根即 BASE_DIR，编排文件在同目录
#   B（旧）：deploy/ 与仓库 NeighInn/ 同级 → 仓库在 ${BASE_DIR}/NeighInn
if [ -f "${SCRIPT_DIR}/docker-compose.prod.yml" ]; then
    REPO_DIR="$BASE_DIR"
    COMPOSE_FILE="${SCRIPT_DIR}/docker-compose.prod.yml"
else
    REPO_DIR="${BASE_DIR}/NeighInn"
    COMPOSE_FILE="${REPO_DIR}/docker-compose.prod.yml"
fi
ENV_FILE="${REPO_DIR}/web/backend/.env.prod"
MOBILE_ARTIFACT_DIR="${BASE_DIR}/artifacts/mobile-h5"
LOG_DIR="${BASE_DIR}/logs"
LOCK_FILE="${BASE_DIR}/.deploy.lock"

# 可选构建配置（例如 PyPI 镜像），不提交到仓库。
if [ -f "${SCRIPT_DIR}/deploy.conf" ]; then
    # shellcheck disable=SC1091
    . "${SCRIPT_DIR}/deploy.conf"
fi
UV_INDEX_URL="${UV_INDEX_URL:-}"

TARGET=""
NO_CACHE=0
PROFILE_ARGS=()

# ---------------------------------------------------------------------------
# 输出与参数
# ---------------------------------------------------------------------------
usage() {
    cat <<'EOF'
用法: deploy.sh <backend|frontend|mobile> [--no-cache]

  backend    构建并部署统一服务端（web/backend，端口 5193）
  frontend   构建并部署 Web 管理端（web/frontend，端口 5192）
  mobile     构建并部署移动端 H5（mobile，端口 80；需预编译产物）

选项:
  --no-cache  构建镜像时不使用 Docker 层缓存
  -h, --help  显示本帮助

可选配置（scripts/deploy.conf）:
  UV_INDEX_URL  PyPI 镜像，用于后端 Docker 构建
                例如 https://pypi.tuna.tsinghua.edu.cn/simple
EOF
}

log_info() { printf '%s [INFO]  %s\n' "$(date '+%F %T')" "$*"; }
log_ok()   { printf '%s [OK]    %s\n' "$(date '+%F %T')" "$*"; }
log_warn() { printf '%s [WARN]  %s\n' "$(date '+%F %T')" "$*" >&2; }
die()      { printf '%s [ERROR] %s\n' "$(date '+%F %T')" "$*" >&2; exit 1; }

parse_args() {
    for arg in "$@"; do
        case "$arg" in
            backend|frontend|mobile)
                [ -z "$TARGET" ] || die "一次只能部署一个组件（已指定: ${TARGET}）"
                TARGET="$arg"
                ;;
            --no-cache) NO_CACHE=1 ;;
            -h|--help) usage; exit 0 ;;
            *) usage >&2; die "未知参数: ${arg}" ;;
        esac
    done
    [ -n "$TARGET" ] || { usage >&2; exit 2; }
}

# ---------------------------------------------------------------------------
# 基础检查
# ---------------------------------------------------------------------------
check_prerequisites() {
    local cmd
    for cmd in git docker curl flock awk sed grep rsync python3; do
        command -v "$cmd" >/dev/null 2>&1 || die "缺少命令: ${cmd}"
    done
    docker compose version >/dev/null 2>&1 || die "未安装 Docker Compose v2（docker compose）"
    docker info >/dev/null 2>&1 || die "无法访问 Docker 守护进程（请用 root 或 docker 组用户运行）"
    [ -d "$BASE_DIR" ] || die "项目根目录不存在: ${BASE_DIR}"
}

setup_logging_and_lock() {
    mkdir -p "$LOG_DIR"
    LOG_FILE="${LOG_DIR}/deploy-$(date '+%Y%m%d-%H%M%S')-${TARGET}.log"
    exec > >(tee -a "$LOG_FILE") 2>&1
    ln -sfn "$LOG_FILE" "${LOG_DIR}/latest.log"
    trap 'rc=$?; printf "%s [ERROR] 部署失败（退出码 %s），日志: %s\n" "$(date "+%F %T")" "$rc" "$LOG_FILE" >&2' ERR

    exec 9>"$LOCK_FILE"
    flock -n 9 || die "已有部署任务在运行（锁文件: ${LOCK_FILE}）"

    log_info "部署目标: ${TARGET}"
    log_info "日志文件: ${LOG_FILE}"
}

# ---------------------------------------------------------------------------
# 拉取代码
# ---------------------------------------------------------------------------
sync_repo() {
    log_info "从 ${REPO_URL} 拉取最新代码（分支 ${BRANCH}）..."
    export GIT_SSH_COMMAND="${GIT_SSH_COMMAND:-ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new}"

    if [ ! -d "${REPO_DIR}/.git" ]; then
        if [ -d "$REPO_DIR" ] && [ -n "$(ls -A "$REPO_DIR" 2>/dev/null)" ]; then
            die "${REPO_DIR} 已存在但不是 git 仓库，请先手动清理或修复后再运行"
        fi
        mkdir -p "$BASE_DIR"
        git clone --branch "$BRANCH" "$REPO_URL" "$REPO_DIR"
    else
        git -C "$REPO_DIR" remote set-url origin "$REPO_URL"
        git -C "$REPO_DIR" fetch --prune origin
        # 强制对齐远端 main：放弃服务器上的代码改动，但保留未被跟踪的 .env.prod 与 H5 产物。
        git -C "$REPO_DIR" checkout -f -B "$BRANCH" "origin/${BRANCH}"
        git -C "$REPO_DIR" reset --hard "origin/${BRANCH}"
    fi

    [ -f "$COMPOSE_FILE" ] || die "编排文件不存在: ${COMPOSE_FILE}"
    log_ok "代码已更新: $(git -C "$REPO_DIR" log -1 --pretty='%h %s')"
}

# ---------------------------------------------------------------------------
# 生产配置校验
# ---------------------------------------------------------------------------
env_value() {
    local key="$1"
    awk -v k="$key" -F= '$1 == k { sub(/^[^=]*=/, ""); print; exit }' "$ENV_FILE"
}

validate_env() {
    [ -f "$ENV_FILE" ] || die "缺少生产配置文件: ${ENV_FILE}
请在仓库目录 web/backend/ 下创建 .env.prod（参考 .env.example 的生产段），
或从已有备份恢复后重试。该文件不会被 git pull/reset 删除。"
    [ -r "$ENV_FILE" ] || die "无权读取 ${ENV_FILE}（请用 root 或文件属主运行）"

    if git -C "$REPO_DIR" ls-files --error-unmatch web/backend/.env.prod >/dev/null 2>&1; then
        die "安全风险：web/backend/.env.prod 已被 git 跟踪，请从仓库移除后再部署"
    fi

    local app_env secret db_url
    app_env="$(env_value APP_ENV)"
    [ "$app_env" = "prod" ] || die "${ENV_FILE} 中 APP_ENV 必须为 prod（当前: ${app_env:-<空>}）"

    secret="$(env_value SECRET_KEY)"
    [ "${#secret}" -ge 32 ] || die "${ENV_FILE} 中 SECRET_KEY 长度不足 32 字符"
    case "$secret" in
        *change-me*|*请替换*) die "${ENV_FILE} 中 SECRET_KEY 仍为占位值，请替换为强随机值" ;;
    esac

    db_url="$(env_value DATABASE_URL)"
    [ -n "$db_url" ] || die "${ENV_FILE} 缺少 DATABASE_URL"
    [ -n "$(env_value MINIO_ENDPOINT)" ] || die "${ENV_FILE} 缺少 MINIO_ENDPOINT"

    log_ok "生产配置校验通过: ${ENV_FILE}"
}

check_middleware_ports() {
    local port name
    for entry in "5205:PostgreSQL" "5201:Redis" "5206:MinIO"; do
        port="${entry%%:*}"
        name="${entry#*:}"
        if timeout 2 bash -c "echo > /dev/tcp/127.0.0.1/${port}" 2>/dev/null; then
            log_ok "${name} (127.0.0.1:${port}) 可访问"
        else
            log_warn "${name} (127.0.0.1:${port}) 不可访问，后端可能启动失败"
        fi
    done
}

# ---------------------------------------------------------------------------
# Docker Compose 操作
# ---------------------------------------------------------------------------
compose() {
    docker compose --project-directory "$REPO_DIR" -f "$COMPOSE_FILE" "$@"
}

deploy_service() {
    local service="$1"
    if [ "$NO_CACHE" -eq 1 ]; then
        log_info "构建镜像（--no-cache）: ${service}"
        compose "${PROFILE_ARGS[@]}" build --no-cache "$service"
        log_info "启动容器: ${service}"
        compose "${PROFILE_ARGS[@]}" up -d --no-build --no-deps "$service"
    else
        log_info "构建并启动容器: ${service}"
        compose "${PROFILE_ARGS[@]}" up -d --build --no-deps "$service"
    fi
}

apply_migration_compat_patch() {
    local ctx="$1"
    local patched

    patched="$(python3 - "$ctx" <<'PY'
import sys
from pathlib import Path

versions = Path(sys.argv[1]) / "alembic" / "versions"
patched = []

p8 = versions / "0008_help_service_review_media.py"
source = p8.read_text(encoding="utf-8")
if '_fresh_schema' not in source and 'get_columns("help_requests")' not in source:
    old = '''    op.add_column("help_requests", sa.Column("media", media_type, nullable=False,
                                             server_default=default))
    op.add_column("help_requests", sa.Column("cover_key", sa.String(255), nullable=False,
                                             server_default=""))
    op.add_column("help_requests", sa.Column("media_type", sa.String(16), nullable=False,
                                             server_default="GALLERY"))
'''
    new = '''    existing_columns = {col["name"] for col in sa.inspect(bind).get_columns("help_requests")}
    if "media" not in existing_columns:
        op.add_column("help_requests", sa.Column("media", media_type, nullable=False,
                                                 server_default=default))
    if "cover_key" not in existing_columns:
        op.add_column("help_requests", sa.Column("cover_key", sa.String(255), nullable=False,
                                                 server_default=""))
    if "media_type" not in existing_columns:
        op.add_column("help_requests", sa.Column("media_type", sa.String(16), nullable=False,
                                                 server_default="GALLERY"))
'''
    if old not in source:
        sys.exit("0008 patch target not found; update scripts/deploy.sh")
    p8.write_text(source.replace(old, new, 1), encoding="utf-8")
    patched.append(p8.name)

p9 = versions / "0009_broadcast_effective_window.py"
source = p9.read_text(encoding="utf-8")
if '_fresh_schema' not in source and 'get_columns("broadcasts")' not in source:
    old = '''    op.add_column("broadcasts", sa.Column("expires_at", sa.DateTime(timezone=True),
                                          nullable=True))
'''
    new = '''    existing_columns = {col["name"] for col in sa.inspect(op.get_bind()).get_columns("broadcasts")}
    if "expires_at" not in existing_columns:
        op.add_column("broadcasts", sa.Column("expires_at", sa.DateTime(timezone=True),
                                              nullable=True))
'''
    if old not in source:
        sys.exit("0009 patch target not found; update scripts/deploy.sh")
    p9.write_text(source.replace(old, new, 1), encoding="utf-8")
    patched.append(p9.name)

print(",".join(patched))
PY
)"
    if [ -n "$patched" ]; then
        log_warn "已应用迁移兼容补丁: ${patched}（上游 0001 按最新模型建表，0008/0009 重复加列）"
    fi
}

build_backend_image() {
    local repo_context="${REPO_DIR}/web/backend"
    local build_context="${SCRIPT_DIR}/.build/backend-context"
    local cache_args=()

    [ "$NO_CACHE" -eq 1 ] && cache_args+=(--no-cache)

    # 使用独立构建上下文：需要对 uv.lock 与迁移脚本做兼容处理，
    # 既不修改仓库文件，也避免把 .env.prod 等敏感文件留在构建目录。
    rm -rf "$build_context"
    mkdir -p "$build_context"
    rsync -a \
        --exclude '.venv/' \
        --exclude '__pycache__/' \
        --exclude '*.pyc' \
        --exclude '.env.prod' \
        "${repo_context}/" "${build_context}/"

    apply_migration_compat_patch "$build_context"

    if [ -n "$UV_INDEX_URL" ]; then
        local index_host
        index_host="$(printf '%s' "$UV_INDEX_URL" | sed -E 's#^(https?://[^/]+).*#\1#')"
        [ -n "$index_host" ] || die "无法解析 UV_INDEX_URL: ${UV_INDEX_URL}"
        log_info "后端构建使用 PyPI 镜像: ${UV_INDEX_URL}"
        # uv.lock 固定了 files.pythonhosted.org 的完整下载地址，必须同步改写；
        # 镜像与官方站点文件路径一致，且 uv 会按 lock 中的 hash 校验内容。
        sed -i \
            -e "s#https://pypi.org/simple#${UV_INDEX_URL%/}#g" \
            -e "s#https://files.pythonhosted.org#${index_host}#g" \
            "${build_context}/uv.lock"
        if grep -qE 'pypi\.org|files\.pythonhosted\.org' "${build_context}/uv.lock"; then
            die "uv.lock 中的 PyPI 地址替换失败，请检查 UV_INDEX_URL"
        fi
    fi

    log_info "构建后端镜像: neighinn/backend:latest"
    docker build "${cache_args[@]}" -f "${build_context}/Dockerfile" \
        -t "neighinn/backend:latest" "$build_context"

    rm -rf "$build_context"
}

wait_for_health() {
    local service="$1"
    local timeout="${2:-180}"
    local cid="" status="" health="" deadline=$((SECONDS + timeout))

    log_info "等待 ${service} 健康检查通过（最多 ${timeout}s）..."
    while [ "$SECONDS" -lt "$deadline" ]; do
        cid="$(compose "${PROFILE_ARGS[@]}" ps -q "$service" 2>/dev/null | head -n1 || true)"
        if [ -n "$cid" ]; then
            status="$(docker inspect -f '{{.State.Status}}' "$cid" 2>/dev/null || echo missing)"
            health="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$cid" 2>/dev/null || echo none)"
            case "$status" in
                running)
                    case "$health" in
                        healthy|none)
                            log_ok "${service} 已就绪（${status}/${health}）"
                            return 0
                            ;;
                        unhealthy)
                            log_warn "${service} 健康检查失败（unhealthy）"
                            break
                            ;;
                    esac
                    ;;
                exited|dead)
                    log_warn "${service} 容器未运行（${status}）"
                    break
                    ;;
            esac
        fi
        sleep 2
    done

    log_warn "${service} 未在 ${timeout}s 内就绪，最近容器日志："
    if [ -n "$cid" ]; then
        docker logs --tail 100 "$cid" 2>&1 || true
    fi
    return 1
}

# ---------------------------------------------------------------------------
# 移动端 H5 产物
# ---------------------------------------------------------------------------
prepare_mobile_artifacts() {
    local candidates=()
    [ -n "${MOBILE_H5_DIST:-}" ] && candidates+=("$MOBILE_H5_DIST")
    candidates+=(
        "${REPO_DIR}/mobile/unpackage/dist/build/web"
        "${REPO_DIR}/mobile/unpackage/dist/build/h5"
        "$MOBILE_ARTIFACT_DIR"
    )

    local src="" candidate
    for candidate in "${candidates[@]}"; do
        [ -n "$candidate" ] || continue
        if [ -f "${candidate}/index.html" ]; then
            src="$candidate"
            break
        fi
    done

    if [ -z "$src" ]; then
        die "未找到移动端 H5 构建产物（需要 index.html）。
uni-app x 必须在 HBuilderX 中编译，Linux 服务器无法构建源码，请：
  1. 在 HBuilderX 打开 mobile/，把 config/env.ts 的 CURRENT_ENV 改为 'docker'；
  2. 发行 → 网站-PC Web或手机H5，输出到 mobile/unpackage/dist/build/web；
  3. 把产物上传到本机任一目录后重新运行本脚本：
       ${MOBILE_ARTIFACT_DIR}
       ${REPO_DIR}/mobile/unpackage/dist/build/web
     或用 MOBILE_H5_DIST=/path/to/dist ./deploy.sh mobile 指定。"
    fi

    local dest="${REPO_DIR}/mobile/unpackage/dist/build/web"
    if [ "$src" != "$dest" ]; then
        log_info "复制 H5 产物: ${src} -> ${dest}"
        rm -rf "$dest"
        mkdir -p "$dest"
        cp -a "${src}/." "$dest/"
    fi

    [ -f "${dest}/index.html" ] || die "H5 产物缺少 index.html: ${dest}"
    if grep -rIl --include='*.js' '127.0.0.1:5193' "$dest" >/dev/null 2>&1; then
        die "H5 产物仍指向 127.0.0.1:5193（local 环境）。
请在 HBuilderX 中把 mobile/config/env.ts 的 CURRENT_ENV 改为 'docker' 后重新发行。"
    fi
    log_ok "H5 产物校验通过: ${dest}"
}

# ---------------------------------------------------------------------------
# 烟雾测试
# ---------------------------------------------------------------------------
backend_alive() {
    curl -fsS --max-time 3 "http://127.0.0.1:5193/health/live" >/dev/null 2>&1
}

expect_contains() {
    local url="$1" pattern="$2" desc="$3" body=""
    if ! body="$(curl -fsS --max-time 10 "$url" 2>/dev/null)"; then
        log_warn "${desc} 失败：请求无响应（${url}）"
        return 1
    fi
    if printf '%s' "$body" | grep -Eq "$pattern"; then
        log_ok "${desc}"
        return 0
    fi
    log_warn "${desc} 失败：响应未匹配 ${pattern}（${url}）"
    return 1
}

test_backend() {
    local failed=0
    expect_contains "http://127.0.0.1:5193/health/live" \
        '"status"[[:space:]]*:[[:space:]]*"ok"' "后端健康检查 /health/live" || failed=1
    expect_contains "http://127.0.0.1:5193/health/ready" \
        '"status"[[:space:]]*:[[:space:]]*"ready"' "后端健康检查 /health/ready" || failed=1
    # categories 会查询 PostgreSQL，可同时验证数据库连通与迁移结果。
    expect_contains "http://127.0.0.1:5193/api/v1/categories" \
        'itemCategories' "后端业务接口 /api/v1/categories（含数据库查询）" || failed=1
    return "$failed"
}

test_static_site() {
    local port="$1" name="$2" desc="$3"
    local body=""
    if ! body="$(curl -fsS --max-time 10 "http://127.0.0.1:${port}/" 2>/dev/null)"; then
        log_warn "${name} 首页请求失败（http://127.0.0.1:${port}/）"
        return 1
    fi
    if printf '%s' "$body" | grep -Eq 'id="app"'; then
        log_ok "${name} 首页可访问（http://127.0.0.1:${port}/）"
    else
        log_warn "${name} 首页内容异常（未找到 id=\"app\"）"
        return 1
    fi
    log_info "${desc}"
    return 0
}

test_api_proxy() {
    local port="$1" name="$2"
    if ! backend_alive; then
        log_warn "后端 5193 未就绪，跳过 ${name} 的 /api 反向代理测试"
        return 0
    fi
    expect_contains "http://127.0.0.1:${port}/api/v1/categories" \
        'itemCategories' "${name} 反向代理 /api/v1 -> 127.0.0.1:5193（含数据库查询）"
}

test_frontend() {
    local failed=0
    test_static_site 5192 "Web 管理端" "入口: http://<服务器IP>:5192" || failed=1
    test_api_proxy 5192 "Web 管理端" || failed=1
    return "$failed"
}

test_mobile() {
    local failed=0
    test_static_site 80 "移动端 H5" "入口: http://<服务器IP>" || failed=1
    test_api_proxy 80 "移动端 H5" || failed=1
    return "$failed"
}

# ---------------------------------------------------------------------------
# 汇总
# ---------------------------------------------------------------------------
show_status() {
    local ip=""
    ip="$(hostname -I 2>/dev/null | awk '{print $1}')"
    [ -n "$ip" ] || ip="<服务器IP>"

    echo
    log_info "容器状态："
    compose "${PROFILE_ARGS[@]}" ps || true
    echo
    case "$TARGET" in
        backend)
            log_info "访问入口: http://${ip}:5193/api/v1"
            log_info "健康检查: http://${ip}:5193/health/live"
            ;;
        frontend)
            log_info "访问入口: http://${ip}:5192"
            ;;
        mobile)
            log_info "访问入口: http://${ip}"
            ;;
    esac
}

# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
parse_args "$@"
setup_logging_and_lock
check_prerequisites
sync_repo
validate_env

case "$TARGET" in
    backend)
        PROFILE_ARGS=()
        check_middleware_ports
        build_backend_image
        log_info "启动容器: backend"
        compose up -d --no-build --no-deps backend
        wait_for_health backend 300 || die "backend 部署失败"
        test_backend || die "backend 烟雾测试失败"
        ;;
    frontend)
        PROFILE_ARGS=()
        backend_alive || log_warn "后端 5193 尚未就绪；admin-web 可启动，但 /api 反代会返回 502，建议先部署 backend"
        deploy_service admin-web
        wait_for_health admin-web 90 || die "frontend 部署失败"
        test_frontend || die "frontend 烟雾测试失败"
        ;;
    mobile)
        PROFILE_ARGS=(--profile mobile)
        prepare_mobile_artifacts
        backend_alive || log_warn "后端 5193 尚未就绪；mobile-h5 可启动，但 /api 反代会返回 502，建议先部署 backend"
        deploy_service mobile-h5
        wait_for_health mobile-h5 90 || die "mobile 部署失败"
        test_mobile || die "mobile 烟雾测试失败"
        ;;
esac

show_status
log_ok "${TARGET} 部署完成"
