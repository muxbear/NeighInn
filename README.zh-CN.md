# 邻里小栈（NeighInn）

[English](README.md) | **简体中文**

面向同一小区及邻近小区业主的闲置物品共享交易平台 —— 支持免费赠与、物品互换与资金担保交易，AI 质检护航，并提供完整的社区运营后台。

![平台](https://img.shields.io/badge/%E5%B9%B3%E5%8F%B0-Android%20%7C%20iOS%20%7C%20HarmonyOS%20%7C%20%E5%BE%AE%E4%BF%A1%E5%B0%8F%E7%A8%8B%E5%BA%8F%20%7C%20H5-FF7A3D)
![移动端](https://img.shields.io/badge/mobile-uni--app%20x%20%28Vapor%29-6BB88A)
![管理端](https://img.shields.io/badge/admin-Vue%203%20%2B%20Vite-6F59D4)
![服务端](https://img.shields.io/badge/backend-FastAPI%20%2B%20PostgreSQL-009688)
![测试](https://img.shields.io/badge/tests-127%20backend%20%C2%B7%2041%20mobile-brightgreen)
![状态](https://img.shields.io/badge/status-active%20development-orange)
![许可证](https://img.shields.io/badge/license-not%20specified-lightgrey)

## 目录

- [项目简介](#项目简介)
- [功能总览](#功能总览)
- [系统架构](#系统架构)
- [技术栈](#技术栈)
- [仓库结构](#仓库结构)
- [快速开始](#快速开始)
- [端口与账号](#端口与账号)
- [配置说明](#配置说明)
- [接口约定](#接口约定)
- [质量门槛](#质量门槛)
- [文档索引](#文档索引)
- [当前状态与路线图](#当前状态与路线图)
- [参与贡献](#参与贡献)
- [安全说明](#安全说明)
- [许可证](#许可证)

## 项目简介

邻里小栈是一个社区型 O2O 闲置物品共享交易平台：同一小区或邻近小区（默认 3 km 内）的认证业主在线上发现物品、线下验货交割。物品上架前需通过 AI 质检；低置信度或风险项进入人工复核。

平台完整支持三种流转方式：

| 交易方式 | 流程 |
| --- | --- |
| **免费赠与** | 申请 → 对方确认 → 预约见面 → 线下交割 |
| **物品互换** | 填写期望交换物品后申请 → 对方确认 → 预约见面 → 当面互换 |
| **货币担保** | 买家付款至平台托管 → 线下验货 → 买家确认满意 → 平台放款给卖家 |

移动端与 Web 管理端共用同一个 FastAPI 服务端、同一套领域模型、同一个数据库和同一组状态机。两端通过领域事件与缓存失效保持一致，不做跨端双写。

## 功能总览

### 移动端（40 个页面、42 个组件）

技术基线为 uni-app x Vapor + Vue 3 组合式 API + TypeScript + Pinia，目标平台包括 Android 6.0+、iOS 15+、HarmonyOS 6.0+（API 20+）、微信小程序（基础库 3.7.1+）与 H5（本地开发端口 5191）。

- **注册、认证与信任**
  - 手机号 + 短信验证码，登录与注册意图分离。
  - 新人引导：昵称、头像、意向小区、协议版本留痕。
  - 实名认证与业主证明；支持审核中、补充材料、驳回重提与认证结果页。
  - 认证中心集中展示实名、住户认证与审核状态。
- **发现与社区**
  - 首页工作台：专属区、小区喇叭站轮播、小区拾物、邻里互助、小区生活流。
  - 附近小区与附近物品，默认 3 km 半径，展示 Haversine 距离。
  - 关键词搜索与筛选，四个专属区（赠与 / 互换 / 出售 / 邻里互助）。
  - 物品详情：媒体轮播、卖家信任面板、留言、收藏、私信、三种交易入口与互换选择。
- **发布与 AI 质检**
  - 三步发布流程，支持草稿、最多 12 张照片、视频与凭证上传、AI 帮写占位能力。
  - AI 质检报告覆盖图像质量、图文一致性、合规性、成色建议四个维度。
  - AI 质检进度/报告页；高置信度走快车道，否则进入人工复核。
  - 「我的发布」支持编辑回填并重新走 AI 质检，覆盖上架、下架、续期、删除全生命周期。
- **交易全流程**
  - 免费赠与、物品互换、货币担保三种完整流程。
  - 收银台、预约/改期、验货双方确认、72 小时未操作自动放款。
  - 评价、纠纷、钱包（余额、托管、可提现金额）。
- **社交与通知**
  - 好友与好友申请（实名门禁、数量上限）。
  - 一对一 IM：已读回执、内容安全提醒与违禁拦截、`client_msg_id` 幂等。
  - 通知中心：分类、未读数、分类设置持久化。
  - 物品、内容、用户举报入口。
- **个人中心与安全**
  - 资料编辑、内置头像库、收藏与足迹、信用中心。
  - 小区管理、帮助中心、设置页、自定义五 Tab 底栏（中央发布按钮）。
  - 统一网络层：Bearer Token、刷新令牌续期、幂等键、错误码映射、GET 重试；WebSocket 心跳与指数退避重连。

### 管理端（Vue 3，23 个侧边栏模块）

- **工作台**
  - 小区切换、核心指标、近 7 日活跃趋势、住户结构、最新动态。
  - 实时待办队列（认证、物品复核、互助、举报、报修），侧边栏徽标同步。
- **社区运营**
  - 社区喇叭：新建/编辑、定时发布、发布、下架、审核状态。
  - 社区物品：检索、复核、推荐、下架、批量操作、交易方式筛选。
  - 邻里互助：求助与邻里服务、审核、撮合、完成、关闭。
  - 社区生活：审核、发布/下线（评论治理由服务端 API 提供）。
- **社区管理**
  - 行政区划树与社区新增/编辑/停用；坐标必填、联系方式加密，停用后移动端不可见。
  - 社区业主目录、住户认证审核队列（通过、驳回且原因有最小长度、要求补充材料；纠正小区由服务端 API 支持）。
- **资金与治理**
  - 资金看板、资金流水、提现双人复核、对账管理、订单只读快照。
  - 纠纷调解：真实冻结托管；结论支持继续履约、退款、强制放款、部分退款、信用处置、冻结账号；资金类结论进入双人复核。
  - 举报工作台：驳回、下架内容、删除留言、禁言、封禁。
- **触达中心**
  - 公告管理：发布即下发站内通知，并提供阅读统计。
  - 通知任务：目标预估、发送、投递明细。
- **系统管理**
  - 用户管理：控制台支持检索与启用/停用；服务端 API 另提供 360° 详情、警告/禁言/限发/限交易/封禁与解除。
  - RBAC 角色与权限树、页面资源管理、运行时参数配置（管理员账号管理由服务端 API 提供）。
  - 参数保存并发布后立即下发移动端 AppConfig；审计日志与 CSV 报表导出任务可用（导出页面仍为占位）。
- **扩展功能**
  - 报事报修：派单、完成。
  - 投诉建议：回复、关闭。
  - 报表导出页面及四个社区扩展模块仍为占位页。
- **访问控制**
  - HttpOnly Cookie 会话、CSRF 双提交与登录失败锁定；TOTP 双因素认证与一次性恢复码已在服务端实现（绑定界面待补）。
  - 路由与菜单按权限控制，仓储按数据范围过滤，审计日志只追加不可改删。

### 统一服务端

- **领域模型**：70 张表，按限界上下文分文件组织，由 9 个 Alembic 迁移管理。
- **状态机**：8 个状态机（物品、订单、认证、提现、资金调整、纠纷、内容、互助），唯一状态变更入口为 `web/backend/src/domain/state.py`。
- **接口契约**：C 端 104 个接口（`/api/v1`），管理端 173 个接口（`/api/v1/admin`）。

| 契约 | 领域模块 |
| --- | --- |
| C 端 `/api/v1` | 认证 · 目录 · 首页 · 物品 · 互动 · 生活 · 服务 · 喇叭 · 订单 · 支付 · 钱包 · 通知 · 社交 · 小区 · 用户 · 上传 · 举报 · WebSocket |
| 管理端 `/api/v1/admin` | 认证 · 账号 · 工作台 · 社区 · 业主 · 运营 · 内容 · 触达 · 治理 · 资金 · 系统 · 用户 · 文件 · 导出 |
- **认证**：移动端 JWT Access/Refresh Token；管理端 Cookie 会话 + CSRF + 可选 TOTP。
- **资金**：金额一律整数分；余额只由复式账本 `ledger_entries` 推导；托管、放款、退款、提现、纠纷资金处置全部落账。
- **一致性**：写操作支持 `X-Idempotency-Key`；一物同时仅允许一个有效订单（BR-08）；非法状态迁移直接拒绝。
- **运维**：进程内 Outbox 继电器与超时调度器（支付超时、确认超时、自动放款、物品到期）；RabbitMQ 可选。
- **文件**：MinIO 公开桶 / 私有桶 / 系统桶，私有材料通过短时效签名 URL 访问。
- **可观测性**：结构化日志、`traceId` 全链路注入、敏感字段脱敏、访问日志与慢请求告警。
- **实时通道**：WebSocket `/api/v1/ws`，承载 IM 消息、订单事件、审核事件与通知。
- **质量**：127 个后端测试，覆盖认证注册、住户认证、物品、订单资金、内容社交、管理面、WebSocket、超时任务、Outbox 与 2FA。

> 支付、短信、推送、实人认证、AI 质检等外部服务目前为 Mock 适配器：接口已就位，真实渠道适配器在路线图中。

## 系统架构

```
移动端 uni-app x                 Web 管理端 Vue 3
Android / iOS / HarmonyOS        Vite · 5192
微信小程序 · H5（5191）
        │                               │
        │ /api/v1（JWT Bearer）         │ /api/v1/admin（Cookie + CSRF）
        ▼                               ▼
┌────────────────────────────────────────────────────┐
│            统一 FastAPI 服务端 · 5193              │
│   C 端 API · 管理端 API · WebSocket /api/v1/ws     │
│   状态机 · RBAC · 审计 · 幂等                      │
└───────┬────────────────┬────────────────┬──────────┘
        ▼                ▼                ▼
   PostgreSQL           Redis            MinIO
  （共享业务库）    （会话/验证码）   （公开/私有桶）
        │
        ▼
  Outbox → RabbitMQ（可选）→ 进程内任务
  （超时任务 · Outbox 继电器）
```

## 技术栈

| 层级 | 技术 |
| --- | --- |
| 移动端 | uni-app x Vapor、Vue 3 组合式 API、TypeScript、Pinia 2、SCSS/ucss、Vitest |
| 管理端前端 | Vue 3.5、TypeScript、Pinia、Vue Router 4、Vite 6、SCSS、Lucide、Axios |
| 服务端 | Python 3.11+、FastAPI、SQLAlchemy 2.0 async、Pydantic 2、Alembic、PyJWT、WebSocket |
| 数据与基础设施 | PostgreSQL 16、Redis 7、MinIO、RabbitMQ（可选）、测试用 SQLite |
| 构建与质量 | HBuilderX 5.34、npm、Vitest、uv、ruff、pytest |

## 仓库结构

```
NeighInn/
├── mobile/                     # uni-app x（Vapor）移动端
│   ├── pages/                  # 40 个页面（主包 20 + 分包 20）
│   ├── components/             # 42 个 ni-* 基础组件与业务组件
│   ├── composables/            # useAuth / useIM / usePay / useUpload / useAudit ...
│   ├── services/               # 业务服务层，含 ws.service.ts 长连接
│   ├── api/                    # request.ts + mock.ts + *.api.ts
│   ├── stores/                 # 9 个 Pinia Store
│   ├── models/                 # 接口与模型类型
│   ├── config/                 # 环境、常量、Mock 数据
│   ├── styles/                 # tokens/reset/typography；uni.scss 为唯一全局注入源
│   ├── tests/                  # Vitest 纯逻辑测试
│   └── docs/                   # 移动端详细设计
├── web/
│   ├── backend/                # FastAPI 统一服务端
│   │   ├── src/api/c_end/      # /api/v1（JWT Bearer）
│   │   ├── src/api/admin/      # /api/v1/admin（Cookie + CSRF）
│   │   ├── src/db/models/      # 70 张表，按限界上下文分文件
│   │   ├── src/domain/         # 业务枚举 + 8 个状态机
│   │   ├── src/services/       # 认证 / 物品 / AI 质检 / 订单 / 资金 / IM
│   │   ├── alembic/            # 9 个数据库迁移
│   │   ├── tests/              # 127 个测试
│   │   └── scripts/            # smoke_e2e.py 端到端冒烟
│   ├── frontend/               # Vue 3 管理端
│   └── docs/                   # 后台管理系统详细设计
├── docs/                       # 需求规格、UI/UE 规范、双端评估报告
├── docker-compose.prod.yml     # 生产部署（服务端 / 管理端 / 移动端 H5）
├── DEPLOY.md                   # 生产部署说明
├── CLAUDE.md                   # 本仓库工程指南
└── README.md                   # 英文版 README
```

> 仓库根目录名末尾含不可见字符 **U+200C（ZERO WIDTH NON-JOINER）**。在终端中使用绝对路径时请直接复制，或使用通配符（如 `NeighInn*`），不要手敲。

## 快速开始

### 环境要求

| 工具 | 版本 | 用途 |
| --- | --- | --- |
| Node.js + npm | Node 18+（推荐 20+） | 管理端、移动端静态检查与测试 |
| Python + uv | Python 3.11+、最新版 uv | 统一服务端 |
| HBuilderX | 5.34 | 编译与运行 uni-app x 移动端 |
| Docker + Compose | 可选（仅生产部署） | 构建并部署服务端、管理端与移动端 H5 镜像；见 [DEPLOY.md](DEPLOY.md) |
| PostgreSQL | 16 | 开发库默认值在 `web/backend/.env.dev`，本机覆盖写入 `.env.local` |
| 微信开发者工具 | 可选 | 微信小程序预览 |

### 1. 启动统一服务端

```bash
cd web/backend
# .env（公共配置）与 .env.dev（开发默认值）随仓库提供；
# 本机数据库 / Redis / MinIO 连接串与账号写入 .env.local（已 gitignore）。
uv sync --dev

# 加载顺序：.env → .env.dev（或 .env.prod）→ .env.local（仅非生产环境）。
# 本地开发直接使用上述文件配置的 PostgreSQL / Redis / MinIO，无需 Docker Compose；
# RabbitMQ 可选，留空时 Outbox 事件只写进程日志。

# 执行数据库迁移
uv run alembic upgrade head

# 启动 API（端口 5193）
uv run python run.py
```

说明：

- 本地开发直接连接 `.env.dev` / `.env.local` 中配置的 PostgreSQL / Redis / MinIO；Docker Compose 仅用于生产部署（见 [DEPLOY.md](DEPLOY.md)）。
- Windows 上必须使用 `uv run python run.py`，不要直接 `uvicorn src.main:app`；psycopg 异步驱动需要 `run.py` 中配置的 SelectorEventLoop。
- `APP_ENV=dev` 时，应用会兜底建表并写入开发种子数据（区划、社区、类目、字典、权限、角色、超管、参数、搜索热词）。生产环境必须走 Alembic 迁移，并替换种子超管账号。
- 本地开发管理员账号为 `admin / Admin@2025`，仅限本地开发使用。
- 真机联调时，在 `web/backend/.env.local` 中设置 `APP_HOST=0.0.0.0`，并把移动端 `LOCAL_HOST` 改为电脑局域网 IP。

### 2. 启动管理端

```bash
cd web/frontend
npm install
npm run dev
```

访问 <http://127.0.0.1:5192>。Vite 会把 `/api` 代理到后端 `http://127.0.0.1:5193`。

### 3. 运行移动端

```bash
cd mobile
npm install
npm run check      # TypeScript + .uvue 解析 + 路由/导入校验 + Vitest
```

然后：

1. 用 HBuilderX 5.34 导入 `mobile/` 目录。
2. 如提示安装 `compile-dart-sass` 编译器插件，按提示安装。
3. 在 `manifest.json` 中替换占位的 DCloud AppID 与微信小程序 AppID。
4. 运行到浏览器、微信开发者工具、Android 真机/模拟器，或 iOS/HarmonyOS 工具链。
5. H5 开发端口为 **5191**，已配置 `strictPort`。

环境切换位于 `mobile/config/env.ts`：

- `CURRENT_ENV = 'local'` —— 连接统一服务端 `http://127.0.0.1:5193/api/v1`（默认）。
- `CURRENT_ENV = 'dev'` —— 完全离线 Mock 演示模式。
- Android 模拟器将 `LOCAL_HOST` 改为 `10.0.2.2`；真机使用局域网 IP。
- `CURRENT_ENV = 'docker'` —— H5 由移动端 nginx 镜像同源托管，使用 `/api/v1`；需先由 HBuilderX 生成 `unpackage/dist/build/web`。

### 4. 生产 Docker 部署

三个镜像（`web/backend`、`web/frontend`、`mobile`）、`.env.prod`、host 网络与 HTTPS 要求、移动端 H5 产物步骤见根目录 [DEPLOY.md](DEPLOY.md)。

## 端口与账号

下表中的开发基础设施地址为默认值，实际以 `web/backend/.env.dev` 与 `.env.local` 为准。

| 服务 | 地址 | 说明 |
| --- | --- | --- |
| 移动端 H5 开发服务器 | <http://127.0.0.1:5191> | HBuilderX 运行到 Web |
| 管理端 | <http://127.0.0.1:5192> | Vite 开发服务器 |
| C 端 API | <http://127.0.0.1:5193/api/v1> | JWT Bearer |
| 管理端 API | <http://127.0.0.1:5193/api/v1/admin> | Cookie + CSRF |
| WebSocket | `ws://127.0.0.1:5193/api/v1/ws?token=<accessToken>` | IM、订单、审核、通知 |
| Swagger / OpenAPI | <http://127.0.0.1:5193/docs> | 双端契约完整可见 |
| 健康检查 | `/health/live`、`/health/ready` | 存活与就绪探针 |
| PostgreSQL | `127.0.0.1:5432` | 数据库以 `web/backend/.env.dev` / `.env.local` 为准（开发库示例：`neighinn_dev`） |
| Redis | `127.0.0.1:6379` | 会话、验证码、缓存 |
| MinIO API / 控制台 | `127.0.0.1:9000` / `9001` | 桶 `neighinn-public`、`neighinn-private`、`neighinn-system` |
| RabbitMQ | `127.0.0.1:5672` / `15672` | 可选，用于 Outbox 投递 |
| 本地管理员 | `admin / Admin@2025` | 仅开发环境 |

## 配置说明

服务端按以下顺序分层加载配置：`.env`（公共）→ `.env.dev` 或 `.env.prod`（由 `APP_ENV` 选择）→ `.env.local`（本机覆盖，仅非生产环境）。字段说明见 `.env.example`。关键配置：

| 变量 | 默认值 | 用途 |
| --- | --- | --- |
| `APP_ENV` | `dev` | `dev` 启用自动建表与种子数据 |
| `APP_HOST` / `APP_PORT` | `127.0.0.1` / `5193` | 真机/局域网联调时改为 `0.0.0.0` |
| `DATABASE_URL` | PostgreSQL DSN | 测试与快速冒烟可用 `sqlite+aiosqlite:///...` |
| `REDIS_URL` | 空 | 会话与验证码存储；不可用时自动降级为进程内内存 |
| `SMS_CODE_BACKEND` | `memory` | 推荐 `redis`，重启/多副本不丢验证码 |
| `CORS_ORIGINS` | 5191/5192/5173 | 放行移动端 H5 与管理端来源 |
| `CORS_ORIGIN_REGEX` | 仅开发环境 | 放行私网 IP 来源，便于真机 H5 调试 |
| `MINIO_*` | 本地 MinIO | 公开/私有/系统桶与访问凭据 |
| `AUTH_REQUIRE_2FA` | 示例为 `false` | 已绑定 TOTP 的管理员登录时强制动态码 |
| `AUTH_ENFORCE_CSRF` | `true` | 管理端写操作 CSRF 校验 |
| `ENABLE_SCHEDULER` | `true` | 进程内 Outbox 继电器与超时任务 |
| `SECRET_KEY` | 开发占位值 | **生产必须替换为 32 字节以上强随机值** |

移动端环境配置位于 `mobile/config/env.ts`（`CURRENT_ENV`、`LOCAL_HOST`、`baseUrl`、`wsUrl`）。

## 接口约定

- **统一响应**：所有 JSON 响应为 `{ "code": 0, "message": "...", "data": ..., "traceId": "..." }`，`code === 0` 表示成功。
- **认证**：
  - 移动端：`Authorization: Bearer <accessToken>`，通过 `X-Refresh-Token` 续期。
  - 管理端：HttpOnly Cookie 会话 + `X-CSRF-Token` 双提交校验；启用 2FA 时需动态验证码。
- **幂等**：写操作携带 `X-Idempotency-Key`（UUID）；同一键携带不同请求体会被拒绝。
- **分页**：`page` / `pageSize`（默认 20，最大 50）。
- **时间**：传输层使用 Unix 毫秒；数据库统一存储 UTC。
- **常用错误码**：

| 错误码 | 含义 |
| --- | --- |
| `40001` | 参数校验失败 |
| `40101` | 未登录或 Token 失效 |
| `40301` | 无权限 / CSRF 校验失败 |
| `40302` | 未完成认证或超出数据范围 |
| `40901` | 物品已被预约，或请求处理中 |
| `40902` | 幂等键复用了不同请求体 |
| `40904` | 非法状态迁移 |
| `42201` | AI 质检未通过 |
| `42203` | 双人复核违规 |
| `42204` | 对账差异未处理 |
| `42901` | 触发限流 |
| `50000` | 系统错误 |
| `50301` | 短信通道未配置 |

- **WebSocket 帧**：上行 `MSG_SEND`、`MSG_ACK`、`MSG_READ`、`PING`；下行 `MSG_PUSH`、`ORDER_EVENT`、`AUDIT_EVENT`、`PONG`。

## 质量门槛

服务端：

```bash
cd web/backend
uv run ruff check src tests run.py scripts
uv run pytest -q                 # 127 个测试，SQLite 离线运行
```

对运行中的服务端跑端到端冒烟：

```bash
# 终端 1：启动服务端（以 SQLite 快速模式为例）
DEBUG=false APP_ENV=dev DATABASE_URL="sqlite+aiosqlite:///./dev-smoke.db" uv run python -c "
import asyncio, uvicorn
from src.main import app
asyncio.run(uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=5193)).serve())"

# 终端 2：执行 AC-01 认证闭环
PYTHONIOENCODING=utf-8 uv run python scripts/smoke_e2e.py
```

管理端前端：

```bash
cd web/frontend
npm run typecheck
npm run build
```

移动端：

```bash
cd mobile
npm run check        # 类型检查 + check:uvue + check:links + Vitest（41 个用例）
```

当前尚未配置 CI；`npm run check` 与后端 pytest 套件是现阶段的质量门槛。

## 文档索引

| 文档 | 内容 |
| --- | --- |
| [`CLAUDE.md`](CLAUDE.md) | 仓库工程指南、架构约定与开发规范 |
| [`docs/邻里小栈需求规格说明.md`](docs/邻里小栈需求规格说明.md) | 产品定位、角色权限、业务流程、M01–M07 / W01–W08、AI 能力、接口与数据、非功能要求 |
| [`docs/邻里小栈UIUE设计设计规范-移动端.md`](docs/邻里小栈UIUE设计设计规范-移动端.md) | 移动端设计 Token、组件、深色模式、无障碍、性能 |
| [`docs/邻里小栈双端业务闭环评估报告与优化改造方案.md`](docs/邻里小栈双端业务闭环评估报告与优化改造方案.md) | 双端业务闭环评估与统一服务端改造方案 |
| [`mobile/docs/邻家小栈详细设计说明书-移动端.md`](mobile/docs/邻家小栈详细设计说明书-移动端.md) | 移动端实现直接依据：页面、组件、Token、接口 |
| [`mobile/docs/邻里小栈概要设计说明书-移动端.md`](mobile/docs/邻里小栈概要设计说明书-移动端.md) | 旧版移动端技术架构与接口契约参考 |
| [`web/docs/邻里小栈后台管理系统详细设计说明书.md`](web/docs/邻里小栈后台管理系统详细设计说明书.md) | 管理端 Figma 还原、页面交互、架构、数据库、API、安全、测试 |
| [`mobile/README.md`](mobile/README.md) | 移动端启动与实现说明 |
| [`web/backend/README.md`](web/backend/README.md) | 统一服务端领域覆盖与开发说明 |
| [`web/frontend/README.md`](web/frontend/README.md) | 管理端启动与页面地图 |

移动端 Figma Make 原型：<https://www.figma.com/make/OEw7s8EWAlGNNd4xnjZXkS/NeighInn%E2%80%8CMobile>。

## 当前状态与路线图

| 领域 | 状态 |
| --- | --- |
| **移动端** | 40 个页面、42 个组件已实现；离线 Mock 全流程与本地服务端联调均可用；HBuilderX 5.34 Web 与微信小程序编译已验证；Android 真机验证待完成 |
| **管理端** | 第一版已实现：登录/会话/CSRF、工作台、社区运营与社区管理、住户认证审核、资金与治理、公告/通知任务、用户/RBAC/参数/审计、报事报修、投诉建议；报表导出页与四个社区扩展页仍为占位 |
| **统一服务端** | Phase 0–2 已交付：70 张表、9 个迁移、8 个状态机、双端接口契约、WebSocket、127 个测试 |
| **外部服务** | 支付、短信、推送、实人认证、AI 质检均为 Mock 适配器；真实渠道适配器待接入 |

后续计划：

- 接入真实渠道适配器：支付、短信、推送、实人认证、AI 质检。
- 完善管理端 2FA 绑定向导界面。
- 完善 `sys_pages` 资源页面管理。
- 对账自动化与差异告警。
- Redis Pub/Sub 支持 WebSocket 多副本分发。
- 移动端：支付/实名/一键登录 UTS 插件、Android 真机验证、分享深链、崩溃与埋点上报。
- 移动端：深色模式、长辈模式全局字号放大、微信小程序 SVG 兼容性回归。
- ESLint / Prettier / Stylelint / husky / CI 接入。

## 参与贡献

1. 修改任一模块前，先阅读 `CLAUDE.md` 与对应详细设计文档。
2. 使用功能分支，保持提交聚焦；提交信息采用 Conventional Commits 风格（`feat:`、`fix:`、`docs:`、`refactor:` 等）。
3. 提交 Pull Request 前执行对应端的质量门槛命令。
4. 严禁提交 `web/backend/.env.local`、`web/backend/.env.prod`、`.claude/settings.local.json` 或任何密钥。
5. 涉及资金、认证、隐私、审核的改动，先对照需求规格第 4/7/9 章与详细设计确认规则。

工程红线：

- 所有状态变更必须经 `web/backend/src/domain/state.py` 的状态机，禁止直接 `UPDATE status`。
- 金额一律整数分（`*_cents`）；余额只能由复式账本 `ledger_entries` 推导。
- 管理端路由默认 `require_permission`；仓储按 `data_scope` 过滤。
- 写操作走幂等键；跨端一致性依靠领域事件 + 缓存失效，不做双写。
- 移动端遵循 uni-app x Vapor 约束：页面根节点为 `scroll-view`，布局只用 Flex（禁止 grid/gap/伪元素），文字样式写在 `<text>` 上，微信小程序 WXSS 类名必须为 ASCII。

## 安全说明

如发现安全漏洞，请私下联系维护者，不要公开提交 Issue。报告中请勿包含密钥、认证材料或生产数据。

## 许可证

本仓库当前未包含许可证文件。除另有书面约定外，保留所有权利。如需使用或再分发代码，请联系维护者获取授权。
