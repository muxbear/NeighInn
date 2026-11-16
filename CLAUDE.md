# CLAUDE.md

本文件为 Claude Code 在本仓库工作时的项目指南。适用于仓库根目录及全部子目录。

## 项目概况

**邻里小栈（Neighbor's Inn，项目代码 `NeighInn`）**：面向同一小区及邻近小区业主的闲置物品共享交易平台。线上撮合、线下验货交割（O2O），AI 质检护航，支持**免费赠与 / 物品互换 / 货币担保交易**三种流转方式。

- **当前阶段**：移动端已完成 uni-app x（Vapor）脚手架、设计 Token、41 个组件与 39 个页面（新增注册、新人引导与认证中心），Mock 全流程可跑通；Web 管理端已完成第一版前后端可运行实现（Vue 3 + FastAPI），核心页面与资金/纠纷/审计模块已接入本地开发数据库与 MinIO。
- Web 端真实支付、推送、短信、AI 质检等外部服务仍待接入；移动端真实后端联调与 UTS 插件待接入。

## 仓库结构

```
NeighInn‌/                          # 根目录名末尾含 U+200C
├── .claude/                        # settings.local.json 含密钥，勿提交
├── .gitignore                      # 忽略密钥、依赖与构建产物
├── CLAUDE.md
├── docs/                           # 上游需求与设计文档
│   ├── 邻里小栈需求规格说明.md
│   ├── 邻里小栈概要设计说明书-移动端.md
│   └── 邻里小栈UIUE设计设计规范-移动端.md
├── mobile/                         # 移动端（uni-app x 项目根目录）
│   ├── App.uvue / main.ts / pages.json / manifest.json / uni.scss
│   ├── pages/ components/ composables/ services/ api/ stores/ models/
│   ├── utils/ config/ styles/ static/ tests/ scripts/
│   ├── docs/邻家小栈移动端详细设计方案.md
│   ├── package.json                # 仅用于测试与静态检查
│   └── README.md
├── web/                            # Web 管理端（前后端分离）
│   ├── backend/                    # 统一服务端（C 端 + 管理端共享领域模型）
│   │   ├── src/api/c_end/          # 移动端契约 /api/v1（JWT）
│   │   ├── src/api/admin/          # 管理端契约 /api/v1/admin（Cookie+CSRF）
│   │   ├── src/db/models/          # 46+ 张表（生产 PG / 测试 SQLite 类型变体）
│   │   ├── src/domain/             # 业务枚举 + 8 个状态机
│   │   ├── src/services/           # 认证/物品/AI 质检/订单/资金/参数/IM
│   │   ├── alembic/                # 数据库迁移
│   │   ├── tests/                  # 99 个测试
│   │   └── scripts/smoke_e2e.py    # 真实 HTTP 端到端冒烟
│   ├── frontend/                   # Vue 3 + TypeScript + Pinia + Vite
│   ├── docs/邻里小栈后台管理系统详细设计说明书.md
│   └── README.md
└── docs/                           # 需求、设计与评估文档
```

> **根目录名末尾含不可见字符 U+200C（ZERO WIDTH NON-JOINER）**：`NeighInn‌/`。不要手敲根目录路径，否则可能报“目录不存在”；在 shell 中使用通配符（如 `NeighInn*`）或直接复制已有路径。**子目录 `mobile/`、`web/` 已改为普通名称，不含不可见字符。**

## 文档索引与优先级

| 文档 | 内容 | 何时阅读 |
| --- | --- | --- |
| `mobile/docs/邻家小栈移动端详细设计方案.md` | **移动端实现直接依据**：uni-app x Vapor 基线、Figma 还原 Token、页面/组件规格、交易与认证补充流程、数据模型/接口、非功能与验收 | 移动端任何功能开发前 |
| `web/docs/邻里小栈后台管理系统详细设计说明书.md` | **Web 管理端实现直接依据**：Figma Make 视觉还原、页面/交互、Vue 3 + FastAPI 架构、23 种设计模式、数据库/API/安全/测试 | Web 管理端任何功能开发前 |
| `docs/邻里小栈需求规格说明.md` | 产品定位、角色权限、业务流程、M01–M07 / W01–W08、AI 能力、接口与数据、非功能、错误码 | 业务规则、权限、交易/资金/审核 |
| `docs/邻里小栈概要设计说明书-移动端.md` | 旧版移动端技术架构与接口契约 | 接口契约参考；**技术栈以详细设计方案为准** |
| `docs/邻里小栈UIUE设计设计规范-移动端.md` | 设计 Token、组件、页面、深色模式、无障碍、性能 | 移动端详细设计未覆盖页面的视觉基线 |

冲突裁决（详细设计 1.2）：**Figma Make 原型（布局/样式/文案/交互）> SRS（业务规则）> 概要设计（架构/接口）> UI 规范（未覆盖页面）**。Web 端 Figma 设计稿为紫色后台视觉体系，不要套用移动端品牌橙。

## 移动端技术基线

详细设计方案将移动端技术栈从旧版 **uni-app（Vue 3 + `.vue` + `src/`）** 变更为 **uni-app x 蒸汽模式（Vapor）**：

- 页面/组件使用 `.uvue`；项目根目录组织源码，**不使用 `src/`**；
- **页面滚动**：App 端没有 Web 式页面滚动，所有页面根节点必须是纵向 `scroll-view`（`direction="vertical"` + `style="flex: 1; height: 1px;"`）；不要用根 `view flex:1` 承载长内容；
- 仅组合式 API（`<script setup>`），不支持选项式与 mixin；
- 样式为 SCSS + ucss 子集：仅 class/分组选择器，不支持 Grid、`gap`、伪元素、复杂关系选择器、`:has`、`aspect-ratio`；
- 布局一律 Flex；文字样式必须写在 `<text>` 上；非 Web 端 SVG 不换色，按状态导出多份；
- 最低系统：Android 6.0+ / iOS 15+ / HarmonyOS 6.0+（API 20+）；微信小程序基础库 3.7.1+；
- 状态管理 Pinia 2.x；原生扩展仅 UTS 插件；
- H5 开发端口：**5191**（`manifest.json` 的 `web.devServer.port` 与 `h5.devServer.port` 均已配置；uni-app 解析 H5 时优先取 `web` 节点）。后端 CORS 同时放行 5191/5192/5173 与私网任意端口。

Figma Make 原型：`https://www.figma.com/make/OEw7s8EWAlGNNd4xnjZXkS/NeighInn%E2%80%8CMobile?t=oDXGBVFADNsqDfZu-6`（2026-11-14）。

### 移动端目录与分层

```
pages/          # 39 个页面（主包 + trade/social/pay 分包）
components/     # 41 个 ni-* 基础组件与业务组件（easycom）
composables/    # useAuth / useIM / usePay / useUpload / useLocation / useAudit / useToast ...
services/       # 业务服务层，含 ws.service.ts 长连接
api/            # request.ts + mock.ts + *.api.ts（纯网络层）
stores/         # Pinia：user/app/item/order/social/life/service/community/notification
models/         # 所有接口/模型类型
utils/ config/ styles/ static/ tests/ scripts/
```

依赖方向：`pages → composables → services → api → request`；`stores` 可被 services 与 pages 引用；`models/utils/config` 可被所有层引用。**禁止反向依赖**：`api` 不得引用 `services`；页面不得直接调用 `uni.request`。

### 移动端设计 Token

- **`uni.scss` 是 HBuilderX 全局注入的唯一来源**（Token + mixin 必须直接内联，不能写相对 `@import`）；`styles/tokens.scss` / `styles/mixins.scss` 仅为兼容直接导入的转发文件。
- 所有颜色/字号/间距/圆角/阴影取 Figma 原值，不整体缩放、不近似替换；页面不得硬编码品牌色。
- 深色模式本期未做，Token 已预留；`backdrop-filter` 仅在高性能场景使用（当前用半透明纯色降级）。
- H5 入口为根目录 `index.html`（Vite）；缺失会导致 `launch web` 报“根目录缺少 index.html”。

### 移动端网络与 Mock

- `api/request.ts`：BaseURL、Bearer Token、`X-Refresh-Token` 续期、写操作自动 `X-Idempotency-Key`、统一响应 `{ code, message, data, traceId }`、错误码映射、GET 重试、日志脱敏。
- `config/env.ts`：`CURRENT_ENV = 'local'`（联调统一服务端 5193）；离线演示改为 `dev`（`env.mock = true`）。`LOCAL_HOST` 统一控制本地后端主机：H5/微信开发者工具用 `127.0.0.1`，Android 模拟器用 `10.0.2.2`，真机改为电脑局域网 IP（后端 `APP_HOST` 同步改为 `0.0.0.0`）。
- Mock 路由在 `api/mock.ts`，数据在 `config/mock/data.ts`。切真实后端时关闭 mock 并替换 `baseUrl` / `wsUrl`。
- `services/ws.service.ts`：心跳 30s、指数退避重连、`MSG_PUSH` / `ORDER_EVENT` 等事件由 `App.uvue` 分发；页面不直连长连接。

## Web 管理端工程

### 技术栈与端口

- 前端：Vue 3 + TypeScript + Pinia + Vue Router + Vite + SCSS + Lucide；端口 **5192**。
- 后端：Python 3.11+ + FastAPI + SQLAlchemy 2.0 async + Pydantic 2 + PostgreSQL（psycopg）；端口 **5193**。
- 中间件：Redis（会话/缓存，需配置有效认证信息）、RabbitMQ（未配置时进程内降级）、MinIO（`ni-public` / `ni-private` / `ni-system`）。
- 开发数据库：由 `web/backend/.env` 的 `DATABASE_URL` 指定；开发账号 `admin / Admin@2025`（仅本地）。
- 前端 API 代理：`/api` → `http://127.0.0.1:5193`。

### Web 目录与分层

```text
web/backend/
├── run.py            # Windows SelectorEventLoop 启动入口
├── src/api/          # 路由：auth/dashboard/communities/residents/operations/communication/governance/system/finance/files
├── src/core/         # 配置、会话、安全、依赖、响应、MinIO
├── src/db/           # models / base / seed
├── src/main.py       # FastAPI 应用、CORS、CSRF、异常处理
├── tests/            # pytest smoke test
├── .env              # 本地开发密钥，已 gitignore
└── README.md

web/frontend/
├── src/api/          # Axios 客户端与接口封装
├── src/components/   # StatusBadge / NiDrawer / EmptyState
├── src/config/       # 导航配置
├── src/layouts/      # AppShell（侧边栏、顶栏、命令面板）
├── src/pages/        # 登录、工作台、社区运营、业主、角色、资源、参数、资金、纠纷等
├── src/router/       # 路由与权限守卫
├── src/stores/       # auth / app
├── src/styles/       # tokens.scss / app.scss（Figma 还原）
└── README.md
```

### Web 启动

```bash
# 后端（Windows 必须用 python run.py）
cd web/backend
uv sync --dev
uv run python run.py

# 前端
cd web/frontend
npm install
npm run dev
```

- Web：`http://127.0.0.1:5192`
- 管理端 API：`http://127.0.0.1:5193/api/v1/admin`
- 移动端 API：`http://127.0.0.1:5193/api/v1`
- Swagger：`http://127.0.0.1:5193/docs`

> **注意**：Windows 上不要直接 `uvicorn src.main:app`，否则 psycopg 异步驱动会因 ProactorEventLoop 启动失败；`run.py` 已处理 SelectorEventLoop。

### Web 已实现范围

登录/会话/CSRF、工作台、社区喇叭、社区物品、邻里互助、社区生活、公告、通知任务、社区运维、社区业主、用户、角色权限、资源管理、参数配置、审计日志、资金看板/流水/提现/对账/订单、纠纷调解、报事报修、投诉建议；详情页与扩展页部分仍为占位。

### Web 设计 Token

- 主色 `#6F59D4`；侧边栏 `#211D38`；页面背景 `#F7F7FA`；卡片边框 `#EBE9EF`；字体 `DM Sans, Noto Sans SC`。
- 侧边栏 248px、顶栏 68px、内容区最大 1500px；8–11px 小字号按 Figma 原值保留，可读性风险见详细设计 R-01。
- **不要用移动端品牌橙 `#FF7A3D` 替换 Web 主色**；后台 Figma 是独立紫色视觉体系。

## 统一服务端（双端共享，Phase 0–2 已交付）

评估结论与改造方案见 `docs/邻里小栈双端业务闭环评估报告与优化改造方案.md`。`web/backend` 是移动端与 Web 后台的**共享服务端**，原独立演示后台已由统一服务端替换。

- **技术栈**：FastAPI + SQLAlchemy 2.0 async + PostgreSQL（测试 SQLite）+ Redis + MinIO + RabbitMQ（Outbox）。
- **端口 5193**：C 端 `/api/v1`（JWT Bearer）；管理端 `/api/v1/admin`（Cookie + CSRF 双提交）；WebSocket `/api/v1/ws`。
- **CORS 与本地联调**：`web/backend/.env` 的 `CORS_ORIGINS` 必须包含移动端 H5（5191）与 Web 前端（5192）；开发环境 `CORS_ORIGIN_REGEX` 放行本机/私网 IP 的任意端口；真机联调把 `APP_HOST` 改为 `0.0.0.0` 并调整移动端 `LOCAL_HOST`。
- **验证码存储**：`SMS_CODE_BACKEND=redis`（推荐，重启/多副本不丢）/ `memory`；非 dev 环境未接短信通道时 `/auth/sms-code` 返回 50301。
- **已实现**：46+ 张表与 Alembic 迁移；8 个状态机；认证（实名/业主证明/审核/冻结联动下架）；物品（发布校验/AI 质检 Mock 适配器/人工复核/快车道）；订单（三种交易方式/BR-08 一物一卖/验货双向确认）；资金（复式账本/托管/放款/退款/提现双人复核/纠纷资金处置）；内容（生活/喇叭/互助/评论审核）；社交（好友/私信 client_msg_id 幂等/内容安全）；通知（公告下发/任务投递/已读）；参数（发布即生效下发 AppConfig）；管理面（社区 CRUD/用户处置/角色权限/管理员账号/审计/导出/举报工作台）；WebSocket 推送。
- **铁律**：状态变更只经 `src/domain/state.py`；金额一律整数分；余额只由 `ledger_entries` 推导；管理端路由默认 `require_permission`；写操作走幂等键；跨端一致性靠事件+缓存失效，不做双写。
- **测试**：`cd web/backend && uv run pytest -q`（99 个测试，覆盖 AC-01/02/05/06/08）；`uv run ruff check src tests run.py scripts`。
- **日志**：统一由 `src/core/logging.py` 配置（开发 console / 生产 JSON，默认仅 stdout）；SQL 日志由 `SQL_ECHO` 独立控制，不再跟随 `DEBUG`；访问日志由应用中间件输出并自动注入 `traceId`，uvicorn 自带 access log 已关闭。
- **双端接线**：移动端 `config/env.ts` → `CURRENT_ENV='local'` 指向 5193；Web 前端 Vite 代理 `/api` → 5193，页面通过 `src/api/compat.ts` 适配统一服务端契约。
- **端到端冒烟**：`PYTHONIOENCODING=utf-8 uv run python scripts/smoke_e2e.py`（对运行中的 5193 执行 AC-01 全链路）。

## 构建与测试

### 移动端

本工程是 **uni-app x 项目**，页面与组件由 HBuilderX 编译；`npm` 仅用于纯逻辑测试与静态检查。

```bash
cd mobile

npm install          # 安装 Pinia / Vitest / TypeScript / Sass / Vue SFC 编译器
npm run check        # type-check + check:uvue + check:links + vitest
npm run type-check   # tsc --noEmit
npm run check:uvue   # 解析 SFC，编译模板/脚本/SCSS
npm run check:links  # 校验路由、相对导入、组件标签
npm test             # Vitest 单元测试
npm run icons        # 重新生成多状态 SVG 图标与内置头像
```

- 开发/真机：HBuilderX 5.34 打开 `mobile/`，运行到 Android/iOS/HarmonyOS/微信开发者工具/浏览器。
  - 已实测：**HBuilderX 5.34 Web 编译通过、微信小程序编译通过**（38 页面 + 40 组件）。
  - H5 开发端口 **5191**（`manifest.json` → `web.devServer.port` / `h5.devServer.port`，含 `strictPort`）；需安装 `compile-dart-sass` 插件（CLI：`cli installPlugin --name compile-dart-sass`）。
  - Android 运行需要连接真机/模拟器；iOS 需 macOS；HarmonyOS 需 DevEco Studio。
- 常用 CLI（安装路径示例 `D:\opt\DCloud\HBuilderX`）：
  - `cli project open --path <项目绝对路径>`
  - `cli launch web --project <项目绝对路径> --browser Chrome`
  - `cli launch mp-weixin --project <项目绝对路径>`
  - `cli launch app-android --project <项目绝对路径> --vaporRenderTarget bytecode`
- `manifest.json` 中 DCloud AppID（`__UNI__04E3A11`）与微信小程序 AppID 为**占位值**，发版前替换。
- 当前没有 ESLint / Prettier / Stylelint / husky / CI；`npm run check` 为现阶段质量门槛。

### Web

```bash
cd web/backend
uv run ruff check src tests run.py scripts
uv run pytest -q

cd ../frontend
npm run typecheck
npm run build
```

## 接口与业务硬性规则

### 接口全局约定（SRS 8.3 / 详细设计 10）

- RESTful + JSON，移动端与 Web 端统一走网关。
- 统一响应 `{ code, message, data, traceId }`，`code === 0` 为成功。
- 认证：移动端 `Authorization: Bearer <accessToken>`；续期 `X-Refresh-Token`；Web 端为 HttpOnly Cookie 会话 + CSRF（设计目标为双因素，开发环境 `AUTH_REQUIRE_2FA=false`）。
- 写操作带幂等键 `X-Idempotency-Key`（UUID）；分页 `page` / `pageSize`（默认 20，最大 50）；时间为 Unix 毫秒。
- 错误码：40001 参数校验失败、40101 未登录/Token 失效、40301 无权限、40302 未完成认证、40901 物品已被预约、42201 AI 质检未通过、42901 限流、50000 系统错误。
- WebSocket JSON 文本帧：上行 `MSG_SEND` / `MSG_ACK` / `MSG_READ` / `PING`；下行 `MSG_PUSH` / `ORDER_EVENT` / `AUDIT_EVENT` / `PONG`。

### 业务边界

- Web 端不提供 C 端交易功能；移动端不提供后台管理功能；两端共用账号体系与服务端 API。
- 业主只能将物品发布到**本小区商店**；邻近小区默认 3 km 内（可配置）。
- 三种交易方式必须完整支持：货币担保支付、免费赠与、物品互换（互换需填写期望交换物品描述）。
- 物品须通过 AI 质检 + 人工复核才可上架；AI 不达标直接驳回并给出改进建议。
- 货币交易走平台担保支付（买家付款至托管，线下验货满意后放款）；GMV 只统计货币交易，赠与/互换单独计件。
- 敏感信息（身份证号、姓名）加密存储、全链路脱敏；照片/凭证存私有桶，短时效签名 URL 访问。
- 涉及资金、认证、隐私、审核的改动，先对照 SRS 第 4/7/9 章与详细设计第 9 章确认规则。

### UI/UX 关键约束

- 移动端品牌主色「琥珀暖橙」`#FF7A3D`；页面背景 `#FAF8F5`；赠与绿 `#6BB88A`、互换蓝 `#5DADE2`、服务金 `#D4A055`。
- 移动端底部 5 Tab：首页 / 附近 / 发布（中央大按钮）/ 消息 / 我的；自定义 TabBar（隐藏原生）+ `ni-tab-bar`。
- Web 管理端主色 `#6F59D4`、侧边栏 `#211D38`、页面背景 `#F7F7FA`；与移动端视觉体系不同，禁止混用。
- 设计原则：温暖、可信、高效、节制；低认知成本（50 岁以上可用、核心路径 ≤ 3 步）；信息渐进式披露。
- 界面文案一律简体中文；金额、距离（10m 级）、耗时（步行/骑行/驾车）的展示格式遵循规范。
- 移动端 6–9px 字号为 Figma 原值，存在可读性风险（详细设计 R-01）；长辈模式已预留开关，全局字号放大尚未实现。
- 微信小程序 WXSS 类名必须为 ASCII：禁止把中文分类/枚举直接拼进 class（会报 `unexpected` 并导致 WXSS 编译失败、页面白屏）；动态类名使用映射后的英文（如 `trade` / `social` / `community`）。

## 当前实现状态与待办

**移动端已完成**：登录/认证、用户注册（手机号验证 + 新人引导 + 协议留痕）、认证中心、实名/住户认证独立提交与认证标识、首页、附近、搜索、四个专属区、物品详情、小区生活/详情、喇叭站、发布物品/生活、AI 质检进度与报告、消息/IM/好友、通知中心、订单（免费/互换/货币）与收银台/预约/验货/评价/纠纷、钱包、我的/资料/头像库/设置、小区管理、收藏足迹、信用中心、帮助与举报；设计 Token、41 个组件、多状态 SVG 图标、Mock 全流程与 Vitest。**HBuilderX 5.34 已验证 Web 与微信小程序编译通过**（Android 待连接设备验证）。

**Web 管理端已完成第一版**：FastAPI + Vue 3 前后端可运行；登录/会话/CSRF、工作台、社区运营四页、公告、通知任务、社区运维、社区业主、住户认证审核与待办铃铛、用户、角色权限、资源管理、参数配置、审计日志、资金看板/流水/提现/对账/订单、纠纷调解、报事报修、投诉建议；PostgreSQL 种子数据、MinIO 私有桶上传与签名 URL、本地构建与 API 冒烟测试通过。**Redis 认证、RabbitMQ、真实支付/短信/Push/AI、2FA 界面、部分新增/编辑抽屉仍待补齐。**

**统一服务端已交付 Phase 0–2 并迁移至 `web/backend`**：统一领域模型（46+ 表）、8 个状态机、双端契约（C 端 82+ 路径 + 管理端 148 路径）、认证/注册引导/物品+AI/订单/资金/内容/社交/通知/参数/管理面全链路真实实现、WebSocket 推送、99 个测试；移动端已切 `local` 环境指向统一服务端，Web 前端已代理到 5193 并经 `compat.ts` 适配。**待办**：真实渠道适配器（支付/短信/推送/实名/AI）、资源页面管理（sys_pages）、对账自动化、2FA 完整向导、Redis Pub/Sub 多副本 WS、性能与安全加固。

**Git 现状**：

- 仓库尚无提交记录（未出生的 `master` 分支）；`docs/`、`.claude/`、`CLAUDE.md`、`mobile/`、`web/` 均未跟踪。
- 已新增根目录 `.gitignore` 与 `web/.gitignore`，忽略 `node_modules/`、`unpackage/`、构建产物、`.claude/settings.local.json` 与 `web/backend/.env`（含密钥，**绝不可提交**）。
- 设计文档规划默认分支为 `main`，与当前 `master` 不一致；初始化提交前先与用户确认分支名。
