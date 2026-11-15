# 邻里小栈统一服务端（web/backend）

**Phase 0 交付：统一领域模型 + Alembic 初始迁移 + 双端 OpenAPI 契约骨架。**

本服务是移动端（C 端业主）与 Web 后台（运营/审核/财务）的**共享服务端**，
落实评估报告的核心结论：一个平台、一套数据、唯一状态机。
本目录现已成为移动端与 Web 管理端唯一的统一服务端。

## 架构

```text
移动端 uni-app x ──/api/v1（JWT Bearer）──┐
                                          ├──► FastAPI 统一服务端
Web 管理端 Vue 3 ──/api/v1/admin（Cookie+CSRF+2FA）──┘
                          │
        ┌─────────────────┼──────────────────┐
        ▼                 ▼                  ▼
   PostgreSQL          Redis              MinIO
  （共享业务库）    （会话/缓存/幂等）   （公私桶/签名 URL）
        │
        ▼
   Outbox → RabbitMQ → Workers（AI 质检/支付回调/超时任务/通知/对账/导出）
```

## 当前状态（Phase 1 进行中）

| 部分 | 状态 |
| --- | --- |
| 领域模型（62 张表） | ✅ 完成（`src/db/models/`，跨库类型变体：生产 JSONB/BigInt、测试 JSON/Integer） |
| Alembic 迁移 | ✅ `0001_initial.py`（初始建表）、`0002_registration_onboarding.py`（注册引导/协议留痕/协议版本参数） |
| 种子数据 | ✅ `src/db/seed.py`（区划/社区/类目/字典/权限/角色/超管/参数/热词，与移动端 Mock 夹具对齐） |
| 状态机（唯一状态变更入口） | ✅ `src/domain/state.py`（8 个状态机 + 15 个单测） |
| 权限/数据范围/审计/幂等 | ✅ `src/core/`（require_permission / data_scope / write_audit / 幂等守卫） |
| **C 端认证域（M01）** | ✅ **真实实现**：短信注册/登录意图分离（`intent=login/register`）、注册新人引导（昵称/头像/意向小区、`onboardingStatus`）、协议版本留痕、JWT 续期、实名/业主证明提交（先实名后证明强校验）、认证状态机、小区绑定查询（mine/nearby/search 含 Haversine 距离） |
| **管理端认证域（W01/W02）** | ✅ **真实实现**：登录（5 次锁定 15 分钟、2FA 通道）、会话/CSRF、认证审核队列（通过/驳回≥10 字/补充材料/纠正小区）、冻结联动自动下架、撤销、全量审计 + 站内通知 + Outbox |
| **C 端物品域（M03/M04）** | ✅ **真实实现**：发布校验（BR-02 本小区绑定/BR-05 照片/BR-06 三交易方式/BR-13 互换描述/M03-01 说明≥20 字/W07 处置联动）、草稿-编辑-重提闭环、AI 质检提交与进度报告、上架/下架/续期/删除、留言（A-09 内容安全拦截）、收藏、距离与三种耗时（SRS 8.2） |
| **AI 质检适配器（SRS 7 章）** | ✅ Mock 流水线：图像质量/图文一致性/合规性/成色建议四维输出 + 置信度 + 风险 + 建议 + trace_id；高置信快车道直上架、低置信/转人工进复核队列；违禁词库与导流敏感检测 |
| **管理端物品复核（W03-01/W03-03/W04-03）** | ✅ **真实实现**：复核队列、AI 报告、通过（可推荐）/驳回（原因必填）/降级、违规下架（通知）、巡检批量下架（成功/失败明细）、两级类目管理 |
| **C 端订单域（M06）** | ✅ **真实实现**：三种交易方式全流程（货币担保支付/赠与/互换）、BR-08 一物一卖（40901）、预约/改期、验货双方确认（满意→放款或交割、不满意必填原因→退款或取消）、取消解锁、互评与信用流水 |
| **C 端支付与钱包（BR-11/M07-05）** | ✅ **真实实现**：预支付下单（幂等防重复支付）、Mock 渠道回调验签（HMAC 双通道确认）、钱包余额/托管/可提现、提现申请（费率/风控/冻结） |
| **复式账本（NF-13）** | ✅ `ledger_entries` 借贷成对、账户余额由账本推导、托管户与收入户隔离（SRS 11.1）、账本驱动的放款/退款/提现全留痕 |
| **管理端资金域（W05-01/W06）** | ✅ **真实实现**：资金看板（真实聚合）、流水查询与账本详情、**提现双人复核**（阈值/风控触发，复核人不同 42203，驳回退回资金）、订单成交快照（只读）、资金处置复核执行 |
| **管理端纠纷调解（W05-02）** | ✅ **真实实现**：双方陈述与证据（签名 URL）、调解时间线、**真实冻结托管**、结论类型（继续履约/退款/强制放款/部分退款/信用/冻结账号）、资金类结论自动生成处置单进入双人复核 |
| **C 端内容与社交域** | ✅ **真实实现**：生活频道（发布→审核→频道可见）、喇叭站（类型映射/收藏/响应）、互助服务（发布/响应去重）、**IM 私信**（client_msg_id 幂等、敏感词风险提醒、违禁拦截、已读）、**好友体系**（实名门禁、申请/同意/拒绝/删除、上限校验）、通知中心（分类/未读/已读/设置持久化）、举报 |
| **管理端内容/触达/治理** | ✅ **真实实现**：喇叭审核发布下架、互助撮合与关闭、生活审核与下线、评论治理、公告（发布即下发站内通知 + 阅读统计）、通知任务（目标预估/发送/投递明细）、举报工作台（下架/删评/禁言/封禁联动）、投诉建议（回复过内容安全） |
| **工作台与参数（W04-05）** | ✅ 工作台全部真实聚合（GMV 仅货币口径，赠与/互换单独计件）；**参数保存→发布→移动端 AppConfig 即时生效**（带缓存与失效）；审计日志只读查询与前后快照 |
| **社区运维（W04-01）** | ✅ 行政区划树、社区新增/编辑（坐标必填、联系方式加密）/停用（移动端即不可见） |
| **用户管理与处置（W07）** | ✅ 用户检索（手机号哈希精确、全链路脱敏）、360° 详情（认证/小区/信用/处置记录）、警告/禁言/限发/限交易/封禁（封禁自动下架在售物品）、解除恢复 |
| **RBAC 自助管理（W01-02）** | ✅ 角色 CRUD（内置保护）、权限授予（非法权限码拦截、超管不可改）、权限树、管理员账号（密码强度/重置/超管保护） |
| **报表导出（W08-03）** | ✅ 导出任务（用户/订单/流水/审计/物品 CSV，默认脱敏）→ 下载写审计 |
| **WebSocket 实时通道** | ✅ `/api/v1/ws`（JWT 鉴权、4401 拒绝未授权、PING/PONG、MSG_READ/MSG_SEND）；`notify_user` 在线推送 NOTIFY；IM 落库即推 MSG_PUSH；生产多副本换 Redis Pub/Sub |
| **时间驱动业务规则** | ✅ 进程内调度器（可关）：30min 未支付自动取消、48h 申请未确认自动取消、**72h 验货确认后自动放款**（买家单方确认即写截止，到期放款+完成+通知）、30 天物品到期自动下架（可续期）；生产替换 Celery/Arq |
| **Outbox 继电器** | ✅ 业务事件事务内落库 → 轮询投递（开发：结构化日志；生产：RabbitMQ persistent）→ PUBLISHED/重试/DEAD；消费幂等表已建 |
| **2FA 完整流程（W01-01）** | ✅ TOTP 绑定（密钥加密存储 + otpauth URI + 8 个一次性恢复码哈希）→ 验证启用 → 登录强制动态码 → **恢复码兜底且一次性消费** |
| 集成测试 | ✅ SQLite 离线全流程（AC-01 全链路、幂等重放、CSRF、冻结联动、撤销），`uv run pytest` 全绿 |
| C 端/管理端其余契约 | ⬜ 路由已声明，handler 抛 501 占位（按 Phase 1 依赖链逐域填充） |
| AI/支付/短信/推送适配器 | ⬜ Phase 1 后续（先 Mock 再真实） |

## 启动

```bash
cd web/backend
uv sync --dev

# 基础设施（PostgreSQL / Redis / MinIO / RabbitMQ）
docker compose up -d

# 建库（首次）
docker compose exec postgres psql -U postgres -c "CREATE DATABASE neighinn_platform;"

# 迁移
uv run alembic upgrade head

# 启动（Windows 必须用 run.py，SelectorEventLoop）
uv run python run.py
```

- C 端 API：<http://127.0.0.1:5193/api/v1>
- 管理端 API：<http://127.0.0.1:5193/api/v1/admin>
- OpenAPI / Swagger：<http://127.0.0.1:5193/docs>（双端契约完整可见）

## 质量门槛

```bash
uv run ruff check src tests run.py scripts
uv run pytest -q            # 87 个测试（状态机/认证注册/物品/订单资金/内容社交/管理面/WS/超时任务/Outbox/2FA）
```

## 双端接线（联调）

| 端 | 配置 | 指向 |
| --- | --- | --- |
| 移动端 | `mobile/config/env.ts` → `CURRENT_ENV = 'local'` | `http://127.0.0.1:5193/api/v1`（`dev` 可切回 Mock） |
| Web 管理端 | `web/frontend/vite.config.ts` 代理 | `/api` → `http://127.0.0.1:5193` |
| WebSocket | `ws://127.0.0.1:5193/api/v1/ws?token=<accessToken>` | 移动端 IM/通知实时推送 |

> **移动端联调注意**
>
> - 移动端 H5 端口为 **5191**（`manifest.json` 的 `web.devServer.port` / `h5.devServer.port`）。
>   `web/backend/.env` 的 `CORS_ORIGINS` 已包含 5191/5192/5173（5173 为 Vite 默认端口兼容）；开发环境 `CORS_ORIGIN_REGEX` 进一步放行本机/私网任意端口，
>   否则浏览器预检会返回 `400 Disallowed CORS origin`。
> - 真机联调：后端 `APP_HOST` 改为 `0.0.0.0`，并把 `mobile/config/env.ts` 的 `LOCAL_HOST` 改为电脑局域网 IP；
>   开发环境 `CORS_ORIGIN_REGEX` 已放行私网 IP 的 H5 来源（生产不生效）。
> - 验证码存储由 `SMS_CODE_BACKEND` 控制：`redis` 重启/多副本不丢（推荐）；`memory` 仅用于无 Redis 的开发降级。
> - Redis 不可用或认证失败时，管理端会话与验证码存储会自动降级为进程内内存（启动日志告警）；补全 `REDIS_URL` 凭据后重启即可启用。
> - 非 `dev` 环境尚未接入真实短信通道，`POST /api/v1/auth/sms-code` 会返回 `50301`，避免“发送成功但收不到”。

**契约适配说明**：

- 移动端 `api/item.api.ts` 的 `toItemPayload` 负责表单中文标签/元 → 服务端枚举/分；
  `api/pay.api.ts` 提现入参自动换算为 `amountCents`；
- Web 端 `src/api/compat.ts` 将平台英文状态码/毫秒时间戳/整数分转换为页面展示体系，
  页面无需改动即可接入；页面重构后逐模块退役该层；
- 预约时间支持 ISO 8601 与移动端预设中文标签（「明天 14:00」「本周六 10:00」）。

## 端到端冒烟（真实 HTTP）

```bash
# 终端 1：SQLite 快速启动（无需 PostgreSQL）
DEBUG=false APP_ENV=dev DATABASE_URL="sqlite+aiosqlite:///./dev-smoke.db" uv run python -c "
import asyncio, uvicorn
from src.main import app
asyncio.run(uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=5193)).serve())"

# 终端 2：跑 AC-01 认证闭环
PYTHONIOENCODING=utf-8 uv run python scripts/smoke_e2e.py
```

覆盖：注册登录（脱敏）→ 实名提交 → 管理端登录（Cookie+CSRF）→ 审核通过 →
业主证明 → 审核通过 → 小区绑定 → 首页聚合 → 通知入账，全链路真实 HTTP 断言。

## 关键设计约束（改造红线）

1. **一个平台、一套数据**：C 端与后台共用 `users/orders/items/wallet_accounts` 等同一批表；后台 API 不返回移动端 Token，移动端不接受后台 Cookie；跨端靠领域事件 + 缓存失效，不做双写。
2. **状态机唯一**：所有状态变更经 `src/domain/state.py` 的 `StateMachine.fire()`，禁止直接 `UPDATE status`；非法迁移返回 40904。
3. **资金红线**：金额一律整数分（`*_cents`）；余额只能通过 `ledger_entries` 复式记账联动；强制放款/退款/划扣必须双人复核（42203）；对账差异未处理禁止关闭（42204）。
4. **权限默认开启**：管理端所有路由挂 `require_permission`；仓储按 `data_scope` 过滤，防 IDOR 返回 40302；越权用例进 CI。
5. **审计默认开启**：审核/配置/导出/资金/敏感查看全部 `write_audit`，只追加不可改删，≥3 年。
6. **幂等默认开启**：写操作带 `X-Idempotency-Key`；同键不同体 40902，处理中 40901。

## 目录

```text
web/backend/
├── alembic/versions/0001_initial.py   # 统一模型初始迁移
├── alembic/versions/0002_registration_onboarding.py  # 注册引导/协议留痕
├── src/
│   ├── main.py                        # 应用入口（双端前缀挂载、中间件、异常映射）
│   ├── core/                          # config / db / responses / security / sessions /
│   │                                  # deps / permissions / idempotency / audit
│   ├── domain/
│   │   ├── enums.py                   # 业务枚举 + 规则默认值（SRS 4.3 / BR-01~14）
│   │   └── state.py                   # 状态机（唯一状态变更入口）
│   ├── db/models/                     # 46 张表，按限界上下文分文件
│   └── api/
│       ├── c_end/                     # 移动端契约（/api/v1，JWT）
│       └── admin/                     # 管理端契约（/api/v1/admin，Cookie+CSRF+2FA）
├── tests/                             # 状态机单测 + OpenAPI 契约冒烟
├── run.py                             # Windows SelectorEventLoop 启动
├── docker-compose.yml                 # PostgreSQL / Redis / MinIO / RabbitMQ
└── .env.example
```

## 下一步（Phase 1，按优先级）

1. 接数据库跑通迁移与种子（区划/类目/字典/权限/角色/超管/参数键树）；
2. C 端认证域（短信登录、实名/业主证明提交、审核状态）+ 管理端认证审核队列；
3. 物品域（发布/媒体/AI 质检适配器/人工复核）；
4. 订单 + 资金域（状态机落地、账本、支付沙箱、提现双人复核）；
5. 管理端路由全部挂 `require_permission` 与审计（骨架已留依赖注入位）。

handler 中每个 `raise not_implemented(...)` 就是一张工作卡；`tests/test_smoke.py`
的契约断言保证填充过程中契约不回退。
