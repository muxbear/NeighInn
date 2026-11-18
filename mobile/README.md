# 邻里小栈移动端（NeighInn Mobile）

面向同一小区及邻近小区业主的闲置物品共享交易平台移动端。项目依据《邻家小栈移动端详细设计方案 v1.0》实现，覆盖物品赠与、物品互换、闲置赚米、邻里互助、小区生活、IM、担保交易、AI 质检、认证与个人中心。

- 技术栈：uni-app x 蒸汽模式（Vapor）+ Vue 3 组合式 API + TypeScript + Pinia + SCSS/ucss
- 目标端：Android / iOS / HarmonyOS / 微信小程序（支付宝小程序、Web 为可选扩展）
- 设计基线：430 × 932，Figma 原值 Token（`uni.scss` 全局注入，`styles/tokens.scss` 兼容转发）
- 当前模式：`CURRENT_ENV = 'local'`，默认联调 `web/backend` 统一服务端（5193）；切回 `dev` 可离线 Mock 全流程演示

## 快速开始（HBuilderX 5.34 已验证）

1. 打开 HBuilderX → **文件 → 导入 → 从本地目录导入**，选择本目录 `mobile/`。
   > 路径含不可见字符 U+200C，请用目录选择器，不要手敲路径。
2. 首次编译如提示安装 **`compile-dart-sass`** 编译器插件，按提示安装；也可在终端执行：
   ```bash
   "D:\opt\DCloud\HBuilderX\cli.exe" installPlugin --name compile-dart-sass
   ```
3. 打开 `manifest.json` 可视化界面，在“基础配置”中**重新获取 DCloud AppID**；微信小程序端填写自己的 AppID（当前为占位值）。
4. 选择运行目标：
   - **Web 预览**：运行 → 运行到浏览器 → Chrome（已验证 HBuilderX 5.34 编译通过；根目录 `index.html` 为 H5 入口；H5 开发端口 **5191**，配置在 `manifest.json` 的 `web.devServer.port` 与 `h5.devServer.port`）
   - **微信小程序**：运行 → 运行到小程序模拟器 → 微信开发者工具（已验证 HBuilderX 5.34 编译通过；需在微信开发者工具“设置 → 安全设置”中开启服务端口）
     > 小程序 WXSS 类名只允许 ASCII，动态 class 不要直接拼中文分类（否则 WXSS 编译失败会白屏）；AppID 需替换为真实值（当前为占位值）。
   - **Android**：手机开启 USB 调试并连接 → 运行 → 运行到手机或模拟器 → 运行到 Android App 基座（Vapor 蒸汽模式）
   - **iOS**：需要 macOS；**HarmonyOS**：需要 DevEco Studio 与 HarmonyOS SDK
5. App 端建议使用 release 包做性能验收（debug 模式性能较差）。

### CLI 运行（可选）

```bash
# 导入项目
"D:\opt\DCloud\HBuilderX\cli.exe" project open --path "D:\work\VSCodeProjects\NeighInn‌\mobile"

# 运行到 Web（Chrome）
"D:\opt\DCloud\HBuilderX\cli.exe" launch web --project "D:\work\VSCodeProjects\NeighInn‌\mobile" --browser Chrome

# 运行到微信小程序（需微信开发者工具已安装并开启服务端口）
"D:\opt\DCloud\HBuilderX\cli.exe" launch mp-weixin --project "D:\work\VSCodeProjects\NeighInn‌\mobile"

# 运行到 Android（需先连接设备，devices list 可查看）
"D:\opt\DCloud\HBuilderX\cli.exe" launch app-android --project "D:\work\VSCodeProjects\NeighInn‌\mobile" --vaporRenderTarget bytecode
```

> 本工程是 uni-app x 项目，**不是** Vite/uni-app CLI 工程，页面与组件由 HBuilderX 编译；`npm` 仅用于纯逻辑测试与静态检查。

## 常用命令

```bash
npm install          # 安装 Pinia 与检查/测试工具
npm run check        # 类型检查 + .uvue 校验 + 路由/导入校验 + Vitest
npm run type-check   # 纯 TS 类型检查（tsc --noEmit）
npm run check:uvue   # 解析 SFC、编译模板/脚本/SCSS
npm run check:links  # 校验路由、相对导入、组件标签
npm test             # Vitest 单元测试
npm run icons        # 重新生成图标与内置头像资源
```

## Docker H5 部署（可选）

uni-app x 的 H5 产物由 HBuilderX 编译，Linux 容器内没有对应编译器，`mobile/Dockerfile` 只托管已编译好的静态文件：

1. 把 `config/env.ts` 的 `CURRENT_ENV` 改为 `'docker'`（使用同源 `/api/v1`，由 nginx 反代到统一服务端）；
2. HBuilderX → **发行 → 网站-PC Web或手机H5**，确认输出到 `unpackage/dist/build/web`；
3. 构建并运行（生产建议使用根目录 `docker-compose.prod.yml`）：

```bash
docker build -t neighinn-mobile ./mobile
docker run -d --name neighinn-mobile --network host \
  -e NGINX_PORT=5191 -e BACKEND_UPSTREAM=http://127.0.0.1:5193 neighinn-mobile
```

访问 `http://<服务器IP>:5191`。nginx 会把 `/api/`（含 WebSocket `/api/v1/ws`）反代到 5193。完整部署步骤见根目录 `DEPLOY.md`。

## Mock 与真实接口

- `config/env.ts`：`CURRENT_ENV = 'local'`（联调统一服务端）；离线演示改为 `dev`（`env.mock = true`）。
- Mock 路由在 `api/mock.ts`，与真实接口保持相同路径与响应形状；数据在 `config/mock/data.ts`。
- `local` 环境的后端主机由 `LOCAL_HOST` 统一配置（默认 `127.0.0.1:5193`）：
  - Web 预览 / 微信开发者工具：`127.0.0.1`；
  - Android 模拟器：`10.0.2.2`；
  - 真机：电脑局域网 IP（如 `192.168.1.100`），同时把 `web/backend/.env` 的 `APP_HOST` 改为 `0.0.0.0`。
- 后端 `CORS_ORIGINS` 必须放行移动端 H5 端口 `5191`，否则浏览器预检会被拒绝；开发环境已用 `CORS_ORIGIN_REGEX` 放宽本机/私网任意端口（详见 `web/backend/README.md`）。
- 开发环境验证码会常驻显示在登录页验证码输入框下方，并输出到后端日志（手机号脱敏）；生产环境不返回验证码。
- 切换到 staging/prod：修改 `CURRENT_ENV`，并把 `mock` 设为 `false`，替换 `baseUrl` / `wsUrl`。
- 首次进入 App 默认停在登录页；开发环境验证码演示码为 `123456`。登录意图不会自动建号，未注册手机号会提示去注册；注册成功后进入新人引导。

## 目录结构

```
App.uvue / main.ts / pages.json / manifest.json / uni.scss
pages/                  40 个页面（主包 + trade/social/pay 等分包）
components/             40 个 ni-* 基础组件与业务组件
composables/            useAuth / useIM / usePay / useUpload / useAudit / useToast ...
services/               业务服务层（含 ws.service 长连接封装）
api/                    纯网络层（request.ts + mock.ts + *.api.ts）
stores/                 Pinia：user/app/item/order/social/life/service/community/notification
models/                 TS 模型与接口协议类型
utils/                  格式化、校验、脱敏、幂等、存储、图片、平台、日志
config/                 环境、常量、Mock 数据
uni.scss                全局注入的 Token + mixin（HBuilderX 自动 import，必须自包含）
index.html              H5 入口（Vite）
styles/                 tokens.scss / reset.scss / mixins.scss / typography.scss
static/                 图标（多状态 SVG）、内置头像、占位图
tests/unit/             Vitest 纯逻辑测试
scripts/                图标生成与 .uvue/路由静态校验脚本
docs/                   详细设计方案
```

## 已实现

- 登录（一键 / 验证码 / 微信，Mock）、用户注册与新人引导（手机号验证、昵称/头像/意向小区、协议留痕）、实名认证、业主证明、认证结果
- 首页 Dashboard（专属区、喇叭站轮播、小区拾物、邻里互助、小区生活）
- 附近、搜索与筛选、专属区（赠与/互换/出售/邻里互助）
- 物品详情（轮播、卖家、留言、收藏、私信、三种交易入口、互换选择）
- 发布物品（三步、草稿、AI 帮写占位、视频/凭证、AI 质检进度与报告）与发布生活
- 小区生活/详情、喇叭站详情、消息、通知中心、好友与申请、IM 会话
- 订单（免费/互换/货币）、收银台、预约、验货、评价、纠纷、钱包
- 我的、个人信息/头像库、设置、小区管理、收藏足迹、信用中心、帮助与举报
- 统一响应/错误码/Token/幂等键/Mock、WebSocket 心跳重连与事件分发
- 设计 Token、41 个组件、多状态 SVG 图标、内置头像库

## Figma 对齐补全（2026-11-14）

- 登录改为首屏（与 Figma `isLoggedIn=false` 一致），补充登录面板切换动画与运营商认证文案
- 登录页右上/左中光晕改为 Figma 径向渐变的柔和 SVG 光晕，移除硬边半圆；内容层级置于光晕之上
- 首页头部右上装饰改为 Figma 径向渐变光晕；喇叭站卡片右下角改为 Figma 的 15px 描边圆环（低透明度），移除实心半圆
- 首页铃铛未读角标改为 Figma 的 15×15 内嵌样式，避免被按钮裁切；发布按钮凸起高度由 25px 下调至 16px
- 个人中心订单类型角标补充 `overflow: visible` 与行高校正，修复“免费/互换/货币订单”数字被图标容器裁切
- 底部 Tab 图标与文字间距由 16px 收紧至 4px，发布文字与其它标签底部对齐
- 首页「邻里互助」按 Figma 重做为紧凑单列服务卡（`service-preview-card`），Tab 补求助/服务彩色圆点，不再复用 260px 横向 service-card
- 首页商品卡信息层级优化：标题 13px 且强制单行省略；图片右下新增距离角标、正文新增绿色距离条突出“最后一公里”；邻里区块改为信任面板，展示同小区/已认证/信用/LV 等级/成交次数；取消卡片与邻里面板描边，改用区块 `#F8F6F3`、卡片白色、邻里面板 `#F4F1EF` 的底色对比；图片高度 164px、内缩 6px 且四角 12px 圆角，卡片高度约 325px
- 生活动态卡媒体同步内缩 6px、四角 12px 圆角；物品详情轮播、生活详情视频/照片集为全宽主媒体，四角均为直角且上下对称；订单/聊天缩略图均四角统一圆角
- Mock 图片切换为 Figma 同款 Unsplash 资源；首页生活流展示 10 条，支持首页关键词即时过滤
- 商品卡补齐业主摘要（头像、认证、信用、成交数、小区）、新交易标签样式与两列网格
- 服务卡补齐时间/地点信息面板、作者信用/服务次数/评价、价格与渐变操作按钮
- 专属区商品按 4 条/页加载、最多 16 条；邻里互助按 4 条递增、最多 12 条
- 通知中心分类角标改为未读数、增加分类图标/列表标题、全部已读禁用态
- 消息页右上角改为好友入口；个人中心统计、内容卡、菜单按 Figma 重构
- 订单互换卡增加“已提交申请 → 对方确认 → 见面互换”三步进度；非货币订单支持预约见面
- 物品详情轮播首尾箭头禁用；生活视频支持播放/暂停状态；头像库三列展示并补名称
- 发布页照片卡增加“拍得越清晰 / AI 检测越准确”提示位
- **「我的发布-编辑」已实现回填并重新走 AI 质检**（不再提示重新发布）
- **全页面根节点改为 `scroll-view`**（`direction="vertical"` + `flex:1;height:1px`），修复 uni-app x App/小程序没有页面级滚动导致首页无法上下滑动的问题
- 已用 HBuilderX 5.34 验证 Web 与微信小程序编译通过，并用浏览器逐页检查登录、首页、专属区、详情、生活、个人中心、通知、消息、订单、发布页

## 待接入（上线前）

- 真实后端网关与 OpenAPI 联调；关闭 Mock
- 支付、推送、一键登录、实人认证的 UTS 插件（支付/实名需服务端签名）
- 分享深链、冷启动恢复、订阅消息、崩溃/埋点上报
- 视频播放 CDN、真实头像上传 OSS
- 微信小程序端 SVG `<image>` 兼容性回归（App 端按方案使用多状态 SVG）
- 深色模式（本期未做，Token 已预留）、长辈模式的全局字号放大落地
- ESLint / Prettier / Stylelint / husky / CI（方案已规划，尚未接入）

## 重要约定

- ucss 仅支持 class 选择器、Flex 布局；**禁止** `grid`、`gap`、伪元素、复杂关系选择器、`aspect-ratio`。
- 所有文字必须放在 `<text>` 中；截图/颜色/字号/圆角取 `uni.scss` Token 原值，不整体缩放。
- **页面滚动**：uni-app x App 端没有 Web 式页面滚动，页面根节点必须是纵向 `scroll-view`（`direction="vertical"` + `style="flex: 1; height: 1px;"`）；新增页面不得再用根 `view flex:1`。
- 页面不直接调用 `uni.request`；分层依赖 `pages → composables → services → api → request`。
- 敏感信息不落明文：Token 统一走 `utils/storage.ts`，App 端上线前替换为 UTS 加密存储。
