# 邻里小栈 · 社区运营管理平台（Web）

前后端分离实现，详细设计见 [`docs/邻里小栈后台管理系统详细设计说明书.md`](./docs/邻里小栈后台管理系统详细设计说明书.md)。

## 目录

```text
web/
├── backend/    # FastAPI + PostgreSQL + Redis + MinIO + RabbitMQ
├── frontend/   # Vue 3 + TypeScript + Pinia + Vite
└── docs/       # 详细设计说明书
```

## 本地启动

### 1. 后端

```bash
cd backend
uv sync --dev
uv run python run.py
```

- API：<http://127.0.0.1:5193/api/v1/admin>
- Swagger：<http://127.0.0.1:5193/docs>
- 首次启动自动建表并写入种子数据。
- 开发账号：`admin / Admin@2025`。

> Windows 必须使用 `python run.py`，不要直接 `uvicorn src.main:app`，否则 psycopg 异步驱动会因 ProactorEventLoop 启动失败。

### 2. 前端

```bash
cd frontend
npm install
npm run dev
```

- 页面：<http://127.0.0.1:5192>
- Vite 将 `/api` 代理到 `http://127.0.0.1:5193`。

## 配置

`backend/.env` 已按本地开发环境配置，**含密钥，已被 `.gitignore` 忽略，禁止提交**。

- PostgreSQL：`neighinn_dev`
- Redis：当前开发实例需要密码，后端自动降级为内存会话；生产环境请补充 `REDIS_URL` 密码。
- MinIO：私有桶 `ni-private`、公开桶 `ni-public`、系统桶 `ni-system`。

## 已实现页面

工作台、社区喇叭、社区物品、邻里互助、社区生活、公告管理、通知任务、社区运维、社区业主、用户管理、角色权限、资源管理、参数配置、审计日志、资金看板/流水/提现/对账/订单、纠纷调解，以及报事报修、投诉建议等扩展页。

## 质量门槛

```bash
cd backend && uv run ruff check app
cd frontend && npm run typecheck && npm run build
```
