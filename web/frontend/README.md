# NeighInn Admin Web

邻里小栈社区运营管理平台前端，按 Figma Make 设计稿还原。

## 技术栈

- Vue 3 + TypeScript + Pinia + Vue Router
- Vite + SCSS（`src/styles/tokens.scss` / `src/styles/app.scss`）
- Lucide Vue Next 图标
- Axios（自动携带 Cookie 与 CSRF Token）

## 启动

```bash
cd frontend
npm install
npm run dev
```

默认地址：<http://127.0.0.1:5192>

Vite 已将 `/api` 代理到 `http://127.0.0.1:5194`，请先启动 backend。

## 构建

```bash
npm run typecheck
npm run build
```

## 登录

- 本地演示账号：`admin / Admin@2025`
- 登录后进入工作台；侧边栏包含 Figma 既有 13 项与本期“资金与治理”扩展分组。

## 页面

- 工作台
- 社区运营：社区喇叭、社区物品、邻里互助、社区生活
- 触达中心：公告管理、通知任务
- 社区管理：社区运维、社区业主
- 资金与治理：资金看板、资金流水、提现管理、对账管理、订单查询、纠纷调解
- 系统管理：用户管理、角色权限、资源管理、参数配置、审计日志、报表导出
- 扩展：报事报修、投诉建议、邻里动态、社区活动、闲置市集、便民服务（占位页，按设计系统继续接入）

## 设计约定

- 主色 `#6F59D4`，侧边栏 `#211D38`，页面背景 `#F7F7FA`；
- 侧边栏 248px、顶栏 68px、内容区最大 1500px；
- 字体 `DM Sans, Noto Sans SC`；
- 8–11px 小字号按 Figma 原值保留，后续通过界面缩放与设计评审处理可读性风险。
