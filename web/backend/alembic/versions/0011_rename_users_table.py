"""0011_rename_users_table — 将 users 表重命名为 platform_users。

背景：`users` 是平台级 C 端账号，与社区级 `residents`、后台 `admin_users`
语义不同。为避免与社区成员档案混淆，统一改名为 `platform_users`。

注意：`0001_initial` 使用当前 ``Base.metadata`` 建表，因此：
- 存量库：表名仍是 ``users``，本迁移执行 rename；
- 由 create_all / 新 metadata 建出的新库：表名已是 ``platform_users``，本迁移跳过。

PostgreSQL 下同步重命名主键、索引、外键约束与自增序列；SQLite 仅重命名表。

revision: 0011_rename_users_table
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0011_rename_users_table"
down_revision = "0010_neighbor_friends"
branch_labels = None
depends_on = None

OLD = "users"
NEW = "platform_users"


def _table_names(bind) -> set[str]:
    return set(sa.inspect(bind).get_table_names())


def _rename_pg_objects(bind, old: str, new: str) -> None:
    """重命名表上的索引、主键、外键约束与自增序列。

    ``op.rename_table`` 只改表名，不会改索引/约束/序列名称；
    名称不一致会给后续迁移和排障带来困扰，因此在 PostgreSQL 下同步处理。
    """
    if bind.dialect.name != "postgresql":
        return

    inspector = sa.inspect(bind)

    # 普通索引 / 唯一索引（SQLAlchemy 默认命名为 ix_<table>_<column>）
    for index in inspector.get_indexes(new):
        name = index.get("name") or ""
        prefix = f"ix_{old}_"
        if name.startswith(prefix):
            target = f"ix_{new}_{name[len(prefix):]}"
            op.execute(sa.text(f'ALTER INDEX "{name}" RENAME TO "{target}"'))

    # 唯一约束（部分历史库可能使用约束而非唯一索引）
    for constraint in inspector.get_unique_constraints(new):
        name = constraint.get("name") or ""
        prefix = f"{old}_"
        if name.startswith(prefix):
            target = f"{new}_{name[len(prefix):]}"
            op.execute(sa.text(
                f'ALTER TABLE "{new}" RENAME CONSTRAINT "{name}" TO "{target}"'
            ))

    # 主键
    pk = inspector.get_pk_constraint(new)
    pk_name = pk.get("name") or ""
    if pk_name.startswith(f"{old}_"):
        target = f"{new}_{pk_name[len(old) + 1:]}"
        op.execute(sa.text(
            f'ALTER TABLE "{new}" RENAME CONSTRAINT "{pk_name}" TO "{target}"'
        ))

    # 本表上的外键约束
    for fk in inspector.get_foreign_keys(new):
        name = fk.get("name") or ""
        if old in name:
            target = name.replace(old, new)
            if target != name:
                op.execute(sa.text(
                    f'ALTER TABLE "{new}" RENAME CONSTRAINT "{name}" TO "{target}"'
                ))

    # 自增序列
    seq = bind.execute(
        sa.text(f"SELECT pg_get_serial_sequence('{new}', 'id')")
    ).scalar()
    if seq:
        seq_name = str(seq).rsplit(".", 1)[-1]
        if seq_name == f"{old}_id_seq":
            op.execute(sa.text(
                f'ALTER SEQUENCE {seq} RENAME TO "{new}_id_seq"'
            ))


def _drop_empty_platform_users(bind) -> None:
    """开发库 create_all 可能已建出空的 platform_users，与存量 users 并存。

    仅当新表为空且无外键引用时删除，随后由本迁移把 users 改名过去。
    """
    count = bind.execute(sa.text(f'SELECT count(*) FROM "{NEW}"')).scalar()
    if count:
        raise RuntimeError(
            f"{NEW} 已有 {count} 行数据，不能自动删除；请人工核对两表数据来源。"
        )
    refs = bind.execute(sa.text(
        "SELECT conrelid::regclass::text FROM pg_constraint "
        f"WHERE confrelid = '{NEW}'::regclass AND contype = 'f'"
    )).scalars().all()
    if refs:
        raise RuntimeError(f"{NEW} 被其他表引用：{refs}；请人工处理。")
    op.drop_table(NEW)


def upgrade() -> None:
    bind = op.get_bind()
    tables = _table_names(bind)
    if OLD not in tables:
        if NEW not in tables:
            raise RuntimeError(
                "既不存在 users 也不存在 platform_users，数据库结构异常，"
                "请先执行 0001_initial 或恢复数据库。"
            )
        # 新库直接由当前 metadata 创建为 platform_users，无需 rename。
        return
    if NEW in tables:
        _drop_empty_platform_users(bind)
    op.rename_table(OLD, NEW)
    _rename_pg_objects(bind, OLD, NEW)


def downgrade() -> None:
    bind = op.get_bind()
    tables = _table_names(bind)
    if NEW not in tables:
        if OLD in tables:
            # 已经处于旧表名，无需回滚。
            return
        raise RuntimeError("platform_users 不存在，无法回滚表名。")
    if OLD in tables:
        raise RuntimeError(
            "users 与 platform_users 同时存在，无法安全回滚；请人工核对。"
        )
    op.rename_table(NEW, OLD)
    _rename_pg_objects(bind, NEW, OLD)
