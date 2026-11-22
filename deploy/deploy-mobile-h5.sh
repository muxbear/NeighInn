#!/usr/bin/env bash
# =============================================================================
# NeighInn 移动端 H5 构建与部署脚本
#
# 功能：
#   1. 与 deploy.sh 相同：从 GitHub 拉取最新 main 分支（丢弃服务器上的代码改动）；
#   2. 使用 /opt/hbuilderx 自带的 uni-app x 编译器构建 H5 生产产物；
#   3. 校验产物后调用 deploy.sh mobile，以 Docker 方式发布（nginx + /api 反代）。
#
# 用法：
#   ./deploy-mobile-h5.sh                 # 构建并部署
#   ./deploy-mobile-h5.sh --build-only    # 只构建，不部署
#   ./deploy-mobile-h5.sh --deploy-only   # 跳过构建，直接部署已有产物
#   ./deploy-mobile-h5.sh --no-cache      # Docker 构建不使用缓存（传给 deploy.sh）
#   ./deploy-mobile-h5.sh -h              # 显示帮助
#
# 关于 HBuilderX：
#   uni-app x 的 H5 产物只能由 HBuilderX 编译。本脚本直接调用 /opt/hbuilderx
#   内置的同一套编译器（plugins/node + plugins/uniapp-cli-vite），等价于在
#   HBuilderX 中「发行 → 网站-PC Web或手机H5」，但无需 GUI，也无需 DCloud 账号。
#
#   不使用 `cli publish web`：该命令要求 HBuilderX 账号在线登录并完成实名认证，
#   无人值守的服务器部署无法保证（实测会返回 "Please Login in!"）。
#
#   可用 HBUILDERX_HOME 覆盖 HBuilderX 安装目录（默认 /opt/hbuilderx）。
#
# 环境处理：
#   构建前会临时把 mobile/config/env.ts 的 CURRENT_ENV 改为 'docker'
#   （同源 /api/v1，由 mobile/nginx.conf 反代到统一服务端），构建结束后恢复原值。
#
# 可选配置（同目录 deploy.conf）：
#   NPM_REGISTRY=https://registry.npmmirror.com
#     mobile/node_modules 缺失时需要 npm ci 安装 sass 等构建依赖，可用该镜像加速。
# =============================================================================
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
BASE_DIR="$(cd -- "${SCRIPT_DIR}/.." && pwd)"

# 兼容两种布局（与 deploy.sh 一致）：
#   A（当前）：deploy/ 位于仓库内部 → 仓库根即 BASE_DIR
#   B（旧）：deploy/ 与仓库 NeighInn/ 同级 → 仓库在 ${BASE_DIR}/NeighInn
if [ -f "${SCRIPT_DIR}/docker-compose.prod.yml" ]; then
    REPO_DIR="$BASE_DIR"
else
    REPO_DIR="${BASE_DIR}/NeighInn"
fi
DEPLOY_SCRIPT="${SCRIPT_DIR}/deploy.sh"
MOBILE_DIR="${REPO_DIR}/mobile"
H5_DIST="${MOBILE_DIR}/unpackage/dist/build/web"
ENV_TS="${MOBILE_DIR}/config/env.ts"
LOG_DIR="${BASE_DIR}/logs"
BUILD_LOCK="${SCRIPT_DIR}/.build/mobile-h5.lock"

REPO_URL="git@github.com:muxbear/NeighInn.git"
BRANCH="main"

# 可选构建配置（例如 NPM_REGISTRY），不提交到仓库。
if [ -f "${SCRIPT_DIR}/deploy.conf" ]; then
    # shellcheck disable=SC1091
    . "${SCRIPT_DIR}/deploy.conf"
fi

HBUILDERX_HOME="${HBUILDERX_HOME:-/opt/hbuilderx}"
HBUILDERX_NODE="${HBUILDERX_HOME}/plugins/node/node"
HBUILDERX_UNI="${HBUILDERX_HOME}/plugins/uniapp-cli-vite/node_modules/@dcloudio/vite-plugin-uni/bin/uni.js"
HBUILDERX_ABOUT="${HBUILDERX_HOME}/plugins/about/package.json"
NPM_REGISTRY="${NPM_REGISTRY:-}"

MODE="all"          # all | build | deploy
NO_CACHE=0
BUILD_TMP=""
ENV_BACKUP=""
ENV_PATCHED=0

# ---------------------------------------------------------------------------
# 输出与参数
# ---------------------------------------------------------------------------
usage() {
    cat <<'EOF'
用法: deploy-mobile-h5.sh [--build-only | --deploy-only] [--no-cache]

  默认        拉取 main 最新代码 → 用 /opt/hbuilderx 构建 H5 → 调用 deploy.sh mobile 部署
  --build-only  只构建 H5，不启动容器
  --deploy-only 跳过构建，直接部署已有 H5 产物（deploy.sh mobile）
  --no-cache    Docker 构建不使用缓存（仅部署阶段有效）
  -h, --help    显示本帮助

环境变量:
  HBUILDERX_HOME  HBuilderX 安装目录（默认 /opt/hbuilderx）
  NPM_REGISTRY    npm 镜像（node_modules 缺失时使用）

可选配置（deploy/deploy.conf）:
  NPM_REGISTRY=https://registry.npmmirror.com
EOF
}

log_info() { printf '%s [INFO]  %s\n' "$(date '+%F %T')" "$*"; }
log_ok()   { printf '%s [OK]    %s\n' "$(date '+%F %T')" "$*"; }
log_warn() { printf '%s [WARN]  %s\n' "$(date '+%F %T')" "$*" >&2; }
die()      { printf '%s [ERROR] %s\n' "$(date '+%F %T')" "$*" >&2; exit 1; }

parse_args() {
    for arg in "$@"; do
        case "$arg" in
            --build-only)
                [ "$MODE" = "all" ] || die "只能指定 --build-only 或 --deploy-only 之一"
                MODE="build"
                ;;
            --deploy-only)
                [ "$MODE" = "all" ] || die "只能指定 --build-only 或 --deploy-only 之一"
                MODE="deploy"
                ;;
            --no-cache) NO_CACHE=1 ;;
            -h|--help) usage; exit 0 ;;
            *) usage >&2; die "未知参数: ${arg}" ;;
        esac
    done
}

# ---------------------------------------------------------------------------
# 日志与并发锁
# ---------------------------------------------------------------------------
setup_logging_and_lock() {
    mkdir -p "$LOG_DIR" "${SCRIPT_DIR}/.build"
    LOG_FILE="${LOG_DIR}/mobile-h5-$(date '+%Y%m%d-%H%M%S').log"
    exec > >(tee -a "$LOG_FILE") 2>&1
    ln -sfn "$LOG_FILE" "${LOG_DIR}/latest-mobile-h5.log"
    trap 'rc=$?; printf "%s [ERROR] 部署失败（退出码 %s），日志: %s\n" "$(date "+%F %T")" "$rc" "$LOG_FILE" >&2' ERR

    exec 9>"$BUILD_LOCK"
    flock -n 9 || die "已有移动端 H5 构建/部署任务在运行（锁文件: ${BUILD_LOCK}）"

    log_info "运行模式: ${MODE}"
    log_info "日志文件: ${LOG_FILE}"
}

cleanup_build_tmp() {
    if [ -n "${BUILD_TMP}" ] && [ -d "${BUILD_TMP}" ]; then
        rm -rf "${BUILD_TMP}"
        BUILD_TMP=""
    fi
}

restore_env_ts() {
    if [ "${ENV_PATCHED}" -eq 1 ] && [ -n "${ENV_BACKUP}" ] && [ -f "${ENV_BACKUP}" ]; then
        cp -p "${ENV_BACKUP}" "${ENV_TS}"
        rm -f "${ENV_BACKUP}"
        ENV_PATCHED=0
        log_info "已恢复 mobile/config/env.ts 原内容"
    fi
}

on_exit() {
    cleanup_build_tmp
    restore_env_ts
}
trap on_exit EXIT

# ---------------------------------------------------------------------------
# 基础检查
# ---------------------------------------------------------------------------
check_common() {
    local cmd
    for cmd in git flock mktemp sed grep find awk du; do
        command -v "$cmd" >/dev/null 2>&1 || die "缺少命令: ${cmd}"
    done
}

check_hbuilderx() {
    [ -x "$HBUILDERX_NODE" ] || die "缺少 HBuilderX 内置 Node: ${HBUILDERX_NODE}
请确认 ${HBUILDERX_HOME} 是完整的 HBuilderX 安装目录（可用 HBUILDERX_HOME 指定）。"
    [ -f "$HBUILDERX_UNI" ] || die "缺少 uni-app x 编译器: ${HBUILDERX_UNI}
请确认 HBuilderX 已安装 uniapp-cli-vite 插件。"
    [ -f "$HBUILDERX_ABOUT" ] || die "缺少 HBuilderX 版本信息: ${HBUILDERX_ABOUT}"

    if [ -z "${HBUILDERX_VERSION:-}" ]; then
        HBUILDERX_VERSION="$(sed -n 's/^[[:space:]]*"version"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' \
            "$HBUILDERX_ABOUT" | head -n1 | tr -d '\r')"
    fi
    [ -n "${HBUILDERX_VERSION}" ] || die "无法从 ${HBUILDERX_ABOUT} 解析 HBuilderX 版本"
    log_ok "HBuilderX 编译器: ${HBUILDERX_HOME}（版本 ${HBUILDERX_VERSION}）"
}

check_docker() {
    command -v docker >/dev/null 2>&1 || die "缺少命令: docker"
    docker compose version >/dev/null 2>&1 || die "未安装 Docker Compose v2（docker compose）"
    docker info >/dev/null 2>&1 || die "无法访问 Docker 守护进程（请用 root 或 docker 组用户运行）"
}

# ---------------------------------------------------------------------------
# 拉取代码（与 deploy.sh 保持一致）
# ---------------------------------------------------------------------------
sync_repo() {
    log_info "从 ${REPO_URL} 拉取最新代码（分支 ${BRANCH}）..."
    export GIT_SSH_COMMAND="${GIT_SSH_COMMAND:-ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new}"

    if [ ! -d "${REPO_DIR}/.git" ]; then
        if [ -d "$REPO_DIR" ] && [ -n "$(ls -A "$REPO_DIR" 2>/dev/null)" ]; then
            die "${REPO_DIR} 已存在但不是 git 仓库，请先手动清理或修复后再运行"
        fi
        mkdir -p "$(dirname "$REPO_DIR")"
        git clone --branch "$BRANCH" "$REPO_URL" "$REPO_DIR"
    else
        if [ -n "$(git -C "$REPO_DIR" status --porcelain --untracked-files=no)" ]; then
            log_warn "检测到未提交的已跟踪文件改动，将重置到 origin/${BRANCH}（未跟踪文件保留）"
        fi
        git -C "$REPO_DIR" remote set-url origin "$REPO_URL"
        git -C "$REPO_DIR" fetch --prune origin
        # 强制对齐远端 main：放弃服务器上的代码改动，但保留未被跟踪的构建产物。
        git -C "$REPO_DIR" checkout -f -B "$BRANCH" "origin/${BRANCH}"
        git -C "$REPO_DIR" reset --hard "origin/${BRANCH}"
    fi

    [ -f "${MOBILE_DIR}/manifest.json" ] || die "未找到移动端工程: ${MOBILE_DIR}"
    log_ok "代码已更新: $(git -C "$REPO_DIR" log -1 --pretty='%h %s')"
}

# ---------------------------------------------------------------------------
# 构建依赖
# ---------------------------------------------------------------------------
ensure_mobile_deps() {
    # HBuilderX 的 compile-dart-sass 插件在本机安装中不完整，H5 构建实际使用
    # 工程内的 sass；node_modules 缺失时先安装，避免构建中途才报预编译器错误。
    if [ -d "${MOBILE_DIR}/node_modules/sass" ]; then
        return 0
    fi

    command -v npm >/dev/null 2>&1 || die "mobile/node_modules 缺少 sass，且系统未安装 npm，无法安装构建依赖"
    log_info "mobile/node_modules 缺少 sass，安装构建依赖（npm ci）..."
    local npm_args=(--no-audit --no-fund)
    [ -n "${NPM_REGISTRY}" ] && npm_args+=(--registry "$NPM_REGISTRY")
    if [ -f "${MOBILE_DIR}/package-lock.json" ]; then
        (cd "$MOBILE_DIR" && npm ci "${npm_args[@]}")
    else
        (cd "$MOBILE_DIR" && npm install "${npm_args[@]}")
    fi
    [ -d "${MOBILE_DIR}/node_modules/sass" ] || die "构建依赖安装失败：仍未找到 node_modules/sass"
    log_ok "移动端构建依赖已就绪"
}

# ---------------------------------------------------------------------------
# 环境切换（CURRENT_ENV=docker）与构建
# ---------------------------------------------------------------------------
prepare_env_ts() {
    [ -f "$ENV_TS" ] || die "缺少环境配置文件: ${ENV_TS}"

    if grep -qE "^export const CURRENT_ENV[^=]*= *'docker'" "$ENV_TS"; then
        log_info "config/env.ts 已为 docker 环境"
        return 0
    fi

    ENV_BACKUP="$(mktemp "${TMPDIR:-/tmp}/neighinn-env.XXXXXX")"
    cp -p "$ENV_TS" "$ENV_BACKUP"
    # 先标记为已修改：即使 sed 失败或后续校验失败，退出时也会从备份恢复。
    ENV_PATCHED=1
    sed -i -E "s/^(export const CURRENT_ENV[^=]*= *)'[^']*'/\1'docker'/" "$ENV_TS"
    if ! grep -qE "^export const CURRENT_ENV[^=]*= *'docker'" "$ENV_TS"; then
        die "无法把 ${ENV_TS} 的 CURRENT_ENV 改为 'docker'，请检查文件格式"
    fi
    log_info "构建期间临时切换 config/env.ts 的 CURRENT_ENV 为 'docker'"
}

build_h5() {
    mkdir -p "$(dirname "$H5_DIST")"
    # 清理上次异常中断留下的临时产物目录。
    find "$(dirname "$H5_DIST")" -mindepth 1 -maxdepth 1 \
        \( -name '.web-build.*' -o -name '.web-old.*' \) \
        -exec rm -rf {} + 2>/dev/null || true
    BUILD_TMP="$(mktemp -d "${MOBILE_DIR}/unpackage/dist/build/.web-build.XXXXXX")"
    chmod 755 "$BUILD_TMP"

    log_info "使用 HBuilderX 编译器构建 H5（uni-app x）..."
    log_info "输入目录: ${MOBILE_DIR}"
    log_info "输出目录: ${BUILD_TMP}"
    # 必须在工程根目录下执行：UTS 插件会以 cwd 解析 tsconfig.json。
    # 日志中可能看到 [plugin:uts] TS2688（找不到 vitest/globals 类型），
    # 这是工程 tsconfig 与 HBuilderX 类型环境的差异，不影响产物，构建仍返回 0。
    if ! (
        cd "$MOBILE_DIR"
        exec env \
            UNI_PROJECT_TYPE=hbuilder \
            UNI_HBUILDERX_PLUGINS="${HBUILDERX_HOME}/plugins" \
            HX_Version="${HBUILDERX_VERSION}" \
            UNI_INPUT_DIR="${MOBILE_DIR}" \
            UNI_OUTPUT_DIR="${BUILD_TMP}" \
            UNI_HBUILDERX_LANGID="zh_CN" \
            NODE_ENV="production" \
            NO_COLOR="1" \
            "${HBUILDERX_NODE}" --no-warnings "${HBUILDERX_UNI}" build -p h5
    ); then
        die "H5 构建失败（完整日志: ${LOG_FILE}）"
    fi
}

validate_h5() {
    local dir="$1" files size
    [ -f "${dir}/index.html" ] || die "H5 构建产物缺少 index.html: ${dir}"

    # 产物若仍指向 local 环境，部署后手机上会访问不到后端。
    if grep -rIl --include='*.js' '127.0.0.1:5193' "$dir" >/dev/null 2>&1; then
        die "H5 产物仍指向 127.0.0.1:5193（local 环境）。
请确认 config/env.ts 的 CURRENT_ENV 能切换为 'docker' 后重试。"
    fi

    if ! grep -rIl --include='*.js' '"/api/v1"' "$dir" >/dev/null 2>&1; then
        log_warn "H5 产物中未找到 /api/v1 同源路径，请确认构建环境为 docker"
    fi

    files="$(find "$dir" -type f | wc -l)"
    [ "$files" -gt 10 ] || die "H5 产物文件数异常（${files} 个），构建可能不完整"
    size="$(du -sh "$dir" | awk '{print $1}')"
    log_ok "H5 产物校验通过（${files} 个文件，${size}）"
}

install_h5() {
    local old="${MOBILE_DIR}/unpackage/dist/build/.web-old.$$"

    rm -rf "$old"
    if [ -e "$H5_DIST" ]; then
        mv "$H5_DIST" "$old"
    fi
    if ! mv "$BUILD_TMP" "$H5_DIST"; then
        [ -e "$old" ] && mv "$old" "$H5_DIST"
        die "替换 H5 产物目录失败: ${H5_DIST}"
    fi
    BUILD_TMP=""
    chmod 755 "$H5_DIST"
    rm -rf "$old"
    log_ok "H5 产物已就绪: ${H5_DIST}"
}

# ---------------------------------------------------------------------------
# 部署
# ---------------------------------------------------------------------------
deploy_h5() {
    [ -f "$DEPLOY_SCRIPT" ] || die "缺少部署脚本: ${DEPLOY_SCRIPT}"
    local args=(mobile)
    [ "$NO_CACHE" -eq 1 ] && args+=(--no-cache)
    log_info "调用 deploy.sh mobile 发布移动端 H5..."
    bash "$DEPLOY_SCRIPT" "${args[@]}"
}

# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
parse_args "$@"
setup_logging_and_lock
check_common

if [ "$MODE" != "deploy" ]; then
    check_hbuilderx
fi
if [ "$MODE" != "build" ]; then
    check_docker
fi

if [ "$MODE" != "deploy" ]; then
    sync_repo
    ensure_mobile_deps
    prepare_env_ts
    build_h5
    restore_env_ts
    validate_h5 "$BUILD_TMP"
    install_h5

    if [ "$MODE" = "build" ]; then
        log_ok "仅构建完成：${H5_DIST}"
        exit 0
    fi
fi

deploy_h5
log_ok "移动端 H5 构建与部署完成"
