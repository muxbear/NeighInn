# syntax=docker/dockerfile:1.7
# 邻里小栈移动端 H5 生产镜像。
#
# uni-app x 的 H5 产物由 HBuilderX 编译，Linux 容器内没有对应编译器，因此本镜像
# 直接托管已编译好的静态产物，不在 Docker 内重复构建。
#
# 构建前置步骤：
#   1. 将 config/env.ts 的 CURRENT_ENV 改为 'docker'（使用同源 /api/v1）；
#   2. HBuilderX → 发行 → 网站-PC Web或手机H5，输出到 unpackage/dist/build/web；
#   3. docker build -t neighinn-mobile ./mobile
# 运行：
#   docker run --rm --network host -e NGINX_PORT=5191 -e BACKEND_UPSTREAM=http://127.0.0.1:5193 neighinn-mobile
FROM nginx:1.27-alpine

# HBuilderX 的 H5 发行目录；若版本输出到 h5 等其他目录，可用 --build-arg 覆盖。
ARG H5_DIST=unpackage/dist/build/web

COPY ${H5_DIST}/ /usr/share/nginx/html/
RUN test -f /usr/share/nginx/html/index.html || \
    (echo "缺少 H5 构建产物：请先在 HBuilderX 中发行到 Web，输出目录 ${H5_DIST}" >&2; exit 1)
# 防止误用 local 环境发行：该环境的 API 地址是 127.0.0.1，只适合本机联调。
# 只检查编译后的 JS，避免把 source map 中的源码注释误判为运行时地址。
RUN found=0; \
    for f in $(find /usr/share/nginx/html -type f -name '*.js'); do \
        if grep -q "127.0.0.1:5193" "$f"; then found=1; break; fi; \
    done; \
    if [ "$found" -eq 1 ]; then \
        echo "H5 产物仍指向 127.0.0.1:5193：请把 config/env.ts 的 CURRENT_ENV 改为 'docker' 后重新发行" >&2; \
        exit 1; \
    fi

COPY nginx.conf /etc/nginx/templates/default.conf.template

# 宿主机网络模式下直接监听 5191，与开发环境端口保持一致。
ENV NGINX_PORT=5191 \
    BACKEND_UPSTREAM=http://127.0.0.1:5193

# 删除镜像自带的 80 端口默认站点，由启动时的 envsubst 模板生成唯一站点配置。
RUN sed -i 's/\r$//' /etc/nginx/templates/default.conf.template \
    && rm -f /etc/nginx/conf.d/default.conf

EXPOSE 5191

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD wget -qO- "http://127.0.0.1:${NGINX_PORT}/" >/dev/null 2>&1 || exit 1

CMD ["nginx", "-g", "daemon off;"]
