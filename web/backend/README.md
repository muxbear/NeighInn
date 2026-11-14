# NeighInn Admin API

邻里小栈社区运营管理平台后端。实现依据：`../docs/邻里小栈后台管理系统详细设计说明书.md`。

## 技术栈

- Python 3.11+ / FastAPI / SQLAlchemy 2.0 async / Pydantic 2
- PostgreSQL 16（psycopg 3）
- Redis 7（不可用时自动降级为进程内会话/缓存；当前开发环境 Redis 需要密码，未配置时使用内存会话）
- MinIO（私有桶 + 预签名 URL，图片异步缩略图接口预留）
- RabbitMQ（可选，当前开发环境未提供连接串时使用进程内事件日志）

## 启动

```bash
cd backend
uv sync --dev
uv run python run.py
```

> Windows 上必须使用 `python run.py`（内部使用 SelectorEventLoop；psycopg 异步驱动不支持 Windows 默认的 ProactorEventLoop）。不要直接使用 `uvicorn src.main:app`。

服务地址：

- API：<http://127.0.0.1:5193/api/v1/admin>
- Swagger：<http://127.0.0.1:5193/docs>
- 健康检查：`/health/live`、`/health/ready`

## 数据库与种子

- `DATABASE_URL` 指向 PostgreSQL；首次启动自动建表并写入 Figma 夹具同款种子数据。
- 种子管理员：`admin / Admin@2025`（仅开发环境，生产必须修改）。
- 已创建 `neighinn_dev` 数据库；如在新环境部署，请先创建数据库：
  ```sql
  CREATE DATABASE neighinn_dev;
  ```
- 迁移策略：当前开发期使用 `Base.metadata.create_all` 快速启动；生产发布前应切换为 Alembic 迁移（设计文档已规划）。

## 对象存储

已创建以下 MinIO bucket：

- `ni-public`：公开图片/封面
- `ni-private`：认证材料、报修照片、反馈附件、纠纷证据、导出文件
- `ni-system`：系统品牌资源

上传接口：`POST /files/presign`（需登录；返回 15 分钟预签名 PUT URL）。

## 已实现模块

- 登录/会话（HttpOnly Cookie + CSRF；开发环境 2FA 开关关闭，可通过 `AUTH_REQUIRE_2FA=true` 开启）
- 工作台汇总/趋势/待办/动态
- 行政区划、社区目录、社区业主档案
- 社区喇叭、社区物品、邻里互助、社区生活
- 公告、通知任务
- 报事报修、投诉建议、纠纷调解
- 用户、角色权限、资源管理、参数配置、审计日志
- 资金看板、资金流水、提现、对账、订单查询
- 统一响应 `{code,message,data,traceId}`、分页、错误码、CSRF、幂等键预留

## 注意

- `.env` 含本地开发密钥，已被 `../.gitignore` 忽略，禁止提交。
- Redis 未认证时启动日志会提示降级，这是预期行为；生产需配置 `REDIS_URL` 与密码。
- 当前 CSRF 中间件对写操作强制校验 `X-CSRF-Token`；前端 Axios 已自动携带 `ni_csrf` Cookie。
