# syntax=docker/dockerfile:1.7
# 邻里小栈 Web 管理端（Vue 3 + Vite）生产镜像：构建静态资源后由 nginx 托管。
# 构建：docker build -t neighinn-admin-web ./web/frontend
# 运行：docker run --rm --network host -e NGINX_PORT=5192 -e BACKEND_UPSTREAM=http://127.0.0.1:5193 neighinn-admin-web
FROM node:22-alpine AS build

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

COPY . .
RUN npm run build

FROM nginx:1.27-alpine AS runtime

# Vite 产物为纯静态文件；nginx 同时把 /api 反向代理到统一服务端。
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/templates/default.conf.template

# 宿主机网络模式下直接监听 5192，与开发环境端口保持一致。
ENV NGINX_PORT=5192 \
    BACKEND_UPSTREAM=http://127.0.0.1:5193

# 删除镜像自带的 80 端口默认站点，由启动时的 envsubst 模板生成唯一站点配置。
RUN sed -i 's/\r$//' /etc/nginx/templates/default.conf.template \
    && rm -f /etc/nginx/conf.d/default.conf

EXPOSE 5192

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD wget -qO- "http://127.0.0.1:${NGINX_PORT}/" >/dev/null 2>&1 || exit 1

CMD ["nginx", "-g", "daemon off;"]
