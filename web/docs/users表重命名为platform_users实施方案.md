# `users` 表重命名为 `platform_users` 实施方案

> **状态**：实施计划（2026-11-19），尚未执行。
> **范围**：`web/backend` 数据库表名、ORM 模型、迁移、测试与文档。
> **前置确认**：需求中的 `flatform_users` 应为 `platform_users` 的拼写笔误。本文统一按 `platform_users` 编写；若确实要保留 `flatform_users`，将下文名称全局替换即可，但**不建议**使用拼写错误的表名。

---

## 0. 本次实施状态（2026-11-19）

已落地：

- `PlatformUser` 模型，表名 `platform_users`；
- 37 处 `ForeignKey("users.id")` 改为 `ForeignKey("platform_users.id")`；
- 新增 `alembic/versions/0011_rename_users_table.py`，兼容「存量库 users」与「新库已是 platform_users」；
- `0002/0004/0006/0008/0009/0010` 增加新库 schema 守卫，避免 `0001` 按新 metadata 建表后历史迁移重复 DDL；
- `0010`/`0011` 增加开发库混合状态处理：仅当预建表为空且无外键引用时删除重建；
- 保留 `User = PlatformUser` 兼容别名，业务层已有 709 处 `User` 引用暂不改动，新代码使用 `PlatformUser`；
- 已在开发库执行 `alembic upgrade head`（0009 → 0011）：`users` 14 行数据完整迁移至 `platform_users`，37 个外键、索引与序列已同步重命名；
- `uv run pytest -q`：**146 passed**；`uv run ruff check src tests run.py scripts alembic`：通过。

待执行：

- 若运行中的后端进程不是 dev reload 模式，重启 `uv run python run.py` 以加载新模型；
- 后续单独提交清理 `User` 别名，将 709 处引用逐步切换为 `PlatformUser`；
- 同步其他文档中的表名表述；
- 删除两个临时文件：根目录 `.tmp_rename_user_refs.py`、`web/backend/scripts/prepare_users_rename.py`（均已置为注释，不再可执行）。

---

## 1. 目标与边界

### 1.1 目标

1. 将数据库表 `users` 重命名为 `platform_users`。
2. 所有引用 `users.id` 的外键同步指向 `platform_users.id`。
3. ORM 模型表名同步修改；可选将模型类 `User` 重命名为 `PlatformUser`，使代码与表名一致。
4. 保证注册、登录、物品、订单、钱包、消息、后台管理等全链路行为不变。

### 1.2 明确不做

以下内容属于外部契约或历史审计，**不随表名变化**，避免破坏前端、移动端和历史数据：

| 保持不变 | 原因 |
| --- | --- |
| API 路径 `/api/v1/users`、`/api/v1/admin/users` | 前端与移动端契约 |
| 响应字段 `userId`、`metrics.users` 等 | 对外 JSON 契约 |
| 权限码 `system:user:*` | 角色权限配置与审计历史 |
| 审计 `resource_type="user"` | 历史审计检索一致性 |
| 表 `admin_users` | 本期只改 C 端账号表，后台账号模型不动 |
| 前端代码 | 不感知数据库表名 |
| 领域动词 `get_current_user`、`find_user_by_phone` | 语义仍是“用户”，无需为表名重命名函数 |

### 1.3 命名建议

- 表名：`platform_users`
- 模型类：`PlatformUser`（推荐，分阶段执行）
- 关联表 `user_penalties`、`credit_logs` 等**表名不变**；它们描述的是“用户相关业务”，不是 `users` 表本身。

---

## 2. 影响面清单

### 2.1 模型与外键

| 文件 | 需修改内容 |
| --- | --- |
| `src/db/models/identity.py` | `User.__tablename__ = "platform_users"`；`Certification`、`Resident`、`UserPenalty`、`CreditLog` 的 `ForeignKey("users.id")` |
| `src/db/models/content.py` | 6 处 `ForeignKey("users.id")` |
| `src/db/models/engagement.py` | 3 处 |
| `src/db/models/funds.py` | 3 处（含 `wallet_accounts.user_id`） |
| `src/db/models/governance.py` | 2 处 |
| `src/db/models/marketplace.py` | 1 处（`items.seller_id`） |
| `src/db/models/notification.py` | 3 处 |
| `src/db/models/social.py` | 11 处 |
| `src/db/models/trade.py` | 4 处（`orders`、`reviews`） |

合计 **37 处** `ForeignKey("users.id")`。修改后应全局搜索确认归零：

```bash
rg 'ForeignKey\("users\.id"\)' web/backend/src
```

### 2.2 ORM 类引用（第二阶段）

- 独立 `User` 类引用：约 **709 处**，分布在 **28 个文件**。
- `CurrentUser` / `OptionalUser` 类型别名引用：约 **118 处**。
- 主要文件：
  - `src/core/deps.py`
  - `src/db/models/identity.py`、`__init__.py`
  - `src/services/auth_service.py`、`chat_service.py`、`item_service.py`、`order_service.py`、`social_service.py`
  - `src/api/admin/*.py`（residents、users、operations、governance、finance、communication、communities、content_ops、dashboard、exports）
  - `src/api/c_end/*.py`（auth、items、life、orders、reports、services、social、ws）
  - `tests/test_admin_system_flow.py`、`tests/test_registration_flow.py`

> 这是机械性重命名，建议单独提交，避免与表名迁移混在一起，降低 review 成本。

### 2.3 原始 SQL

- `src/`、`tests/`、`scripts/` 中没有直接写 `FROM users` / `JOIN users` 的 SQL。
- 历史迁移 `alembic/versions/0010_neighbor_friends.py` 含 `JOIN users ua/ub`；本次未改其 SQL，但增加了 `_fresh_schema` 守卫：新库由 `0001` 直接建出 `platform_users` 时跳过该迁移。
- `0002/0004/0006/0008/0009/0010` 同样增加新库守卫，避免历史迁移在新库上因找不到 `users` 或重复建列而失败。
- 新迁移使用 `op.rename_table`，禁止使用会生成 DROP/CREATE 的 autogenerate。

### 2.4 索引、约束、序列

`ALTER TABLE ... RENAME` 不会自动重命名以下对象，需要在新迁移中处理（PostgreSQL）：

| 对象 | 旧名（示例） | 新名 |
| --- | --- | --- |
| 主键 | `users_pkey` | `platform_users_pkey` |
| 唯一索引 | `ix_users_phone_hash` | `ix_platform_users_phone_hash` |
| 普通索引 | `ix_users_status`、`ix_users_realname_status`、`ix_users_onboarding_status`、`ix_users_intent_community_id` | `ix_platform_users_*` |
| 外键约束 | `fk_users_intent_community`（或 `users_intent_community_id_fkey`） | `fk_platform_users_intent_community` |
| 自增序列 | `users_id_seq` | `platform_users_id_seq` |

> 名称以实际数据库为准。迁移中通过 `sa.inspect(bind)` 读取再重命名，避免硬编码与历史迁移差异冲突。SQLite 不支持直接重命名索引/约束，迁移中用 `dialect.name == "postgresql"` 守卫；测试库由 `Base.metadata.create_all` 按新模型建表，不受影响。

---

## 3. 分阶段实施

### 阶段一：数据库与模型表名（行为不变）

**目标**：只改表名和 37 处外键，业务代码仍使用 `User` 类，风险最低。

1. 修改 `src/db/models/identity.py`：
   ```python
   class User(Entity):
       __tablename__ = "platform_users"
   ```
2. 全局替换 37 处：
   ```text
   ForeignKey("users.id")  →  ForeignKey("platform_users.id")
   ```
3. 新增迁移 `alembic/versions/0011_rename_users_table.py`：
   ```python
   revision = "0011_rename_users_table"
   down_revision = "0010_neighbor_friends"

   def upgrade() -> None:
       op.rename_table("users", "platform_users")
       bind = op.get_bind()
       if bind.dialect.name == "postgresql":
           _rename_pg_objects(bind)

   def downgrade() -> None:
       bind = op.get_bind()
       if bind.dialect.name == "postgresql":
           _rename_pg_objects_back(bind)
       op.rename_table("platform_users", "users")
   ```
4. `_rename_pg_objects` 建议逻辑：
   - 用 `sa.inspect(bind)` 读取 `platform_users` 的索引、主键、外键；
   - 将 `ix_users_*` 重命名为 `ix_platform_users_*`；
   - 将 `users_pkey` 重命名为 `platform_users_pkey`；
   - 将含 `users` 的外键约束重命名为 `fk_platform_users_*`；
   - 查询 `pg_get_serial_sequence('platform_users', 'id')`，若为 `users_id_seq` 则执行 `ALTER SEQUENCE ... RENAME TO platform_users_id_seq`。
5. 运行测试：
   ```bash
   cd web/backend
   uv run pytest -q
   uv run ruff check src tests run.py scripts
   ```
   测试使用 `Base.metadata.create_all`，任何遗漏的 `ForeignKey("users.id")` 都会在 mapper 配置/建表阶段报 `NoReferencedTableError`。

> 注意：当前最新迁移是 `0010`。原计划的「住户后台角色授权」迁移顺延为 `0012_resident_admin_link.py`。

### 阶段二：ORM 类重命名（本次以兼容别名过渡）

**目标**：`User` → `PlatformUser`，让业务层与表名一致。本次已把模型类重命名为 `PlatformUser`，并保留 `User = PlatformUser` 兼容别名；709 处既有引用暂不改动，后续单独提交清理别名。

1. 修改 `src/db/models/identity.py` 类名与 docstring：
   ```python
   class PlatformUser(Entity):
       """平台级 C 端账号（表 platform_users）。"""
       __tablename__ = "platform_users"
   ```
2. 修改 `src/db/models/__init__.py`：
   ```python
   from src.db.models.identity import Certification, CreditLog, PlatformUser, Resident, UserPenalty
   ```
   `__all__` 会自动包含 `PlatformUser`。
3. 全局替换独立的 `User` 引用：
   ```bash
   rg -n '\bUser\b' web/backend/src web/backend/tests web/backend/scripts
   ```
   - 只替换完整的 `User`（词边界），不要动 `AdminUser`、`UserPenalty`、`CurrentUser`、`OptionalUser`、`UserIn` 等包含 `User` 的标识符。
   - 更新导入、类型注解、`select(User)`、`db.get(User, ...)`、`User.phone_hash` 等。
4. `CurrentUser` / `OptionalUser` 的处理二选一：
   - **保守**：保留别名名称，仅把类型改为 `PlatformUser`：
     ```python
     CurrentUser = Annotated[PlatformUser, Depends(get_current_user)]
     OptionalUser = Annotated[PlatformUser | None, Depends(get_optional_user)]
     ```
   - **彻底**：改名为 `CurrentPlatformUser` / `OptionalPlatformUser`，并更新 118 处引用。建议作为独立提交，避免与类重命名混在一起。
5. 保留以下名称不变：
   - `get_current_user`、`get_optional_user`；
   - `find_user_by_phone`、`get_or_create_user_by_phone`；
   - `UserPenalty`（表 `user_penalties` 不变）；
   - `AdminUser`、`admin_users`；
   - API 路径、JSON 字段、权限码、审计 `resource_type`。
6. 运行 `pytest`、`ruff`、后端启动检查。

> 如果希望一次性完成，也可以把阶段一和阶段二合并为一个提交；但 709 处类引用会让 review 很难聚焦，建议分开。

### 阶段三：文档与残留清理

1. 更新文档中的表名表述：
   - `web/docs/邻里小栈后台管理系统详细设计说明书.md`
   - `web/docs/住户后台角色授权与用户账号体系改造方案.md`
   - `web/docs/users表重命名为platform_users实施方案.md`（本文）
   - `CLAUDE.md`、`web/README.md` 如出现 `users` 表名
2. 全局搜索残留：
   ```bash
   rg '__tablename__ = "users"' web/backend/src
   rg 'ForeignKey\("users\.id"\)' web/backend/src
   rg '\bUser\b' web/backend/src web/backend/tests
   ```
3. 确认以下内容**仍然存在且不应被误改**：
   - `GET /api/v1/admin/users`
   - `metrics.users`
   - `system:user:view`
   - `resource_type="user"`

---

## 4. 迁移与发布步骤

### 4.1 发布前

1. 备份数据库（至少 `pg_dump` 目标库）。
2. 确认没有外部 BI/报表/脚本直接查询 `users` 表；如有，同步改为 `platform_users`。
3. 确认发布窗口：`ALTER TABLE RENAME` 需要 `ACCESS EXCLUSIVE` 锁，且旧代码不兼容新表名，必须与后端发布同时进行，不能滚动升级。

### 4.2 发布

```bash
cd web/backend
uv run alembic upgrade head
```

验证：

```sql
-- 表存在
SELECT to_regclass('public.platform_users');

-- 行数与改名一致
SELECT count(*) FROM platform_users;

-- 37 个外键指向新表
SELECT conname, conrelid::regclass AS from_table
FROM pg_constraint
WHERE confrelid = 'platform_users'::regclass AND contype = 'f';

-- 序列
SELECT pg_get_serial_sequence('platform_users', 'id');
```

然后启动后端、跑冒烟：

```bash
PYTHONIOENCODING=utf-8 uv run python scripts/smoke_e2e.py
```

### 4.3 回滚

1. 停止后端（避免旧代码访问新表名）。
2. 执行：
   ```bash
   uv run alembic downgrade -1
   ```
3. 部署上一版本后端。
4. 验证 `users` 表、外键、序列恢复。

> 如果已经产生新数据，回滚迁移只改表名，不会丢数据；但仍建议先备份。

---

## 5. 验证清单

| 检查项 | 命令/方式 | 期望 |
| --- | --- | --- |
| 无旧表名 | `rg '__tablename__ = "users"' src` | 0 条 |
| 无旧外键 | `rg 'ForeignKey\("users\.id"\)' src` | 0 条 |
| 类引用清理 | `rg '\bUser\b' src tests`（阶段二完成后） | 仅允许保留项，最好 0 条 |
| 测试 | `uv run pytest -q` | 全绿 |
| 静态检查 | `uv run ruff check src tests run.py scripts` | 通过 |
| 迁移 | `uv run alembic upgrade head` / `downgrade -1` | 成功 |
| 后端启动 | `uv run python run.py` | 正常 |
| 注册/登录 | 移动端短信注册、登录 | 正常 |
| 后台登录 | admin 登录、工作台 | 正常 |
| 核心链路 | 发布物品、下单、钱包、消息、通知 | 正常 |
| 冒烟 | `scripts/smoke_e2e.py` | 通过 |
| 前端 | `npm run typecheck` / `npm run build` | 通过（预期无改动） |

---

## 6. 风险与应对

| 风险 | 影响 | 应对 |
| --- | --- | --- |
| 遗漏 `ForeignKey("users.id")` | 后端启动/建表报 `NoReferencedTableError` | 全局搜索 + `pytest` 兜底 |
| 使用 autogenerate 生成迁移 | 被识别为 DROP/CREATE，丢数据 | 手写 `op.rename_table`，禁止 autogenerate 直接提交 |
| 索引/约束/序列未改名 | 功能正常但命名不一致，后续迁移易混淆 | 迁移中用 inspector 重命名 |
| SQLite 不支持重命名索引 | 开发库索引名残留 | 迁移按 dialect 守卫；测试库按新模型建表 |
| 类重命名误伤 `AdminUser` / `UserPenalty` | 编译或运行错误 | 使用词边界替换，先跑 `pytest`/`ruff` |
| 旧代码与新表名混跑 | 接口 500 | 维护窗口内同时发布；禁止滚动升级 |
| 外部报表直接查 `users` | 报表失败 | 发布前通知并同步改 SQL |
| `flatform_users` 拼写 | 长期检索/沟通成本 | 统一使用 `platform_users` |

---

## 7. 建议提交拆分

```text
commit 1  refactor(db): rename users table to platform_users
          - identity.py __tablename__
          - 37 处 ForeignKey
          - alembic 0011_rename_users_table.py

commit 2  refactor(backend): rename User model to PlatformUser
          - identity.py 类名
          - models/__init__.py 导出
          - 28 个文件中的独立 User 引用
          - CurrentUser/OptionalUser 类型更新（可选改名）

commit 3  docs: sync platform_users naming
          - 设计文档、README、CLAUDE.md
```

每个提交都应独立通过 `pytest` 与 `ruff`，便于定位问题和回滚。
