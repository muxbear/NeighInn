# 生产部署说明（Docker）

本说明对应三个镜像：统一服务端 `web/backend`、Web 管理端 `web/frontend`、移动端 H5 `mobile`。
生产中间件使用百度云 Redis / PostgreSQL / MinIO，服务端口发布在部署机的 `127.0.0.1` 上：

| 服务 | 端口 | 账号 / 密码 | 说明 |
| --- | --- | --- | --- |
| Redis | 5201 | `default` / 见 `.env.prod` | 会话、短信验证码 |
| PostgreSQL | 5205 | `postgres` / 见 `.env.prod` | 库名 `neighinn_prod` |
| MinIO API | 5206 | `admin` / 见 `.env.prod` | 对象存储 |
| MinIO 控制台 | 5207 | `admin` / 见 `.env.prod` | 仅运维使用，不对公网开放 |

## 1. 前置条件

- Linux 服务器，Docker 24+、Docker Compose v2。
- 中间件已启动，且部署机可通过 `127.0.0.1:5201/5205/5206` 访问。
- PostgreSQL 中已创建数据库 `neighinn_prod`（字符集 UTF-8）。
- 生产配置文件 `web/backend/.env.prod` 已按实际环境填写；该文件已被 `.gitignore` 忽略，**不要提交到仓库**。
- 首次部署前确认并妥善保管 `SECRET_KEY`（新库可用已生成值，迁移库必须沿用旧值）；建议轮换数据库/Redis/MinIO 密码，并修改管理员密码、开启 2FA。

## 2. 构建与启动

管理端 + 统一服务端：

```bash
docker compose -f docker-compose.prod.yml up -d --build
```

移动端 H5（可选，需先生成 H5 产物，见第 4 节）：

```bash
docker compose -f docker-compose.prod.yml --profile mobile up -d --build
```

启动后：

| 入口 | 地址 |
| --- | --- |
| Web 管理端 | `http://<服务器IP>:5192` |
| 移动端 H5 | `http://<服务器IP>:5191` |
| 统一服务端 API | `http://<服务器IP>:5193/api/v1` |
| 管理端 API | `http://<服务器IP>:5193/api/v1/admin` |
| 健康检查 | `http://<服务器IP>:5193/health/live`、`/health/ready` |

单独使用 Dockerfile：

```bash
# 后端（需要 host 网络访问本机中间件）
docker build -t neighinn-backend ./web/backend
docker run -d --name neighinn-backend --network host \
  --env-file web/backend/.env.prod --restart unless-stopped neighinn-backend

# 管理端
docker build -t neighinn-admin-web ./web/frontend
docker run -d --name neighinn-admin-web --network host \
  -e NGINX_PORT=5192 -e BACKEND_UPSTREAM=http://127.0.0.1:5193 \
  --restart unless-stopped neighinn-admin-web

# 移动端 H5
docker build -t neighinn-mobile ./mobile
docker run -d --name neighinn-mobile --network host \
  -e NGINX_PORT=5191 -e BACKEND_UPSTREAM=http://127.0.0.1:5193 \
  --restart unless-stopped neighinn-mobile
```

## 3. 数据库初始化

后端容器的入口脚本会在启动前自动执行 `alembic upgrade head`，失败时重试并在超时后退出。

> `APP_ENV=prod` 时应用**不会**自动建表，也**不会**写入开发种子数据（区划、类目、权限、角色、超管等）。
> 入口脚本会自动执行 `alembic upgrade head`，但数据库本身需要预先创建；迁移完成后，再按既有数据导入流程写入生产基线数据和管理员账号。不要在生产库执行开发种子脚本（内置的 `admin / Admin@2025` 仅供本地开发）。
> 若数据库曾由开发环境 `init_db()` 自动建表且没有 `alembic_version`，不要直接执行 `upgrade`，应先备份并按基线 `stamp` 或重建空库。

## 4. 移动端 H5 产物

uni-app x 的 H5 产物由 HBuilderX 编译，Linux 容器内没有对应编译器，因此移动端镜像只托管预编译产物：

1. 将 `mobile/config/env.ts` 的 `CURRENT_ENV` 改为 `'docker'`；该环境使用同源 `/api/v1`，由 nginx 反代到统一服务端。
2. 在 HBuilderX 中：**发行 → 网站-PC Web或手机H5**，确认输出目录为 `mobile/unpackage/dist/build/web`。若你的 HBuilderX 版本输出到 `unpackage/dist/build/h5`，请把 `mobile/Dockerfile` 中 `ARG H5_DIST` 的默认值改为该目录（或在 `docker build` 时传 `--build-arg H5_DIST=unpackage/dist/build/h5`）。
3. 再执行 `docker compose -f docker-compose.prod.yml --profile mobile up -d --build`。

如需改回真实 App 发版，请把 `CURRENT_ENV` 改回 `staging` 或 `prod` 并填写真实 API 域名。

## 5. 重要注意事项

- **HTTPS**：`APP_ENV=prod` 时管理端会话 Cookie 带 `Secure` 属性，必须通过 HTTPS 访问；建议在 5191/5192 前加 Nginx/Caddy 做 TLS 终止（移动端 H5 的定位、相机等浏览器能力也要求安全上下文）。若只能用 HTTP 联调，可临时把 `APP_ENV` 改为 `staging`（Cookie 不带 Secure），验证后改回 `prod`。
- **MinIO 预签名 URL**：`.env.prod` 中 `MINIO_ENDPOINT=127.0.0.1:5206` 只适用于部署机本机访问。若浏览器或移动端从其他机器访问，必须改成客户端可达的公网 IP/域名（建议 HTTPS 与同源反向代理），否则图片和认证材料 URL 无法加载；HTTPS 页面还必须把 `MINIO_SECURE` 设为 `true` 并配置有效证书，否则会被浏览器混合内容策略拦截。
- **外层反向代理**：若在 5191/5192 前再加 Nginx/Caddy 做 TLS，请为 `/api/v1/ws` 保留 `Upgrade`/`Connection` 头，否则 IM/订单推送的 WebSocket 无法建立。
- **CORS**：管理端与 H5 都通过 nginx 同源反代 `/api`，通常不会触发 CORS。若使用独立域名的 H5 直连后端，请把来源追加到 `CORS_ORIGINS`。
- **数据库账号**：`.env.prod` 按所给信息使用 `postgres` 账号；正式上线建议为应用创建仅拥有 `neighinn_prod` 权限的独立账号，并同步更新 `DATABASE_URL`。
- **SECRET_KEY**：用于 JWT 与敏感字段加密。若生产库是从开发库迁移而来，必须沿用迁移前的 `SECRET_KEY`，否则已加密的身份证号/姓名等字段将无法解密；全新库则可使用 `.env.prod` 中新生成的值，并在上线后妥善保管。
- **多 worker**：当前后端以单进程运行，`ENABLE_SCHEDULER=true` 的 Outbox/超时任务只执行一份。若改为多 worker/多副本，必须把调度器拆为独立进程，避免重复执行。
- **日志**：生产使用 `LOG_FORMAT=json`、仅输出 stdout，按 `docker logs -f neighinn-backend` 或宿主日志采集查看。
