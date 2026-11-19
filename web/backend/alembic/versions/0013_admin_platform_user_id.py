"""0013_admin_platform_user_id — admin_users 关联列改名。

`admin_users.user_id` 指向 `platform_users.id`，与 `residents.user_id`
（住户档案关联）语义易混淆；统一改名为 `platform_user_id`，并同步索引与
外键约束名称。列名调整采用原地重命名，不重建表、不丢数据。

revision: 0013_admin_platform_user_id
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0013_admin_platform_user_id"
down_revision = "0012_resident_admin_link"
branch_labels = None
depends_on = None

TABLE = "admin_users"
OLD = "user_id"
NEW = "platform_user_id"


def _column_names(bind) -> set[str]:
    return {item["name"] for item in sa.inspect(bind).get_columns(TABLE)}


def _rename_pg_objects(bind, old: str, new: str) -> None:
    """同步重命名索引、唯一约束与外键约束（PostgreSQL）。"""
    if bind.dialect.name != "postgresql":
        return
    inspector = sa.inspect(bind)

    for index in inspector.get_indexes(TABLE):
        name = index.get("name") or ""
        if index.get("column_names") == [old] and old in name and new not in name:
            target = name.replace(old, new)
            op.execute(sa.text(f'ALTER INDEX "{name}" RENAME TO "{target}"'))

    for constraint in inspector.get_unique_constraints(TABLE):
        name = constraint.get("name") or ""
        if constraint.get("column_names") == [old] and old in name and new not in name:
            target = name.replace(old, new)
            op.execute(sa.text(
                f'ALTER TABLE "{TABLE}" RENAME CONSTRAINT "{name}" TO "{target}"'
            ))

    for fk in inspector.get_foreign_keys(TABLE):
        name = fk.get("name") or ""
        if old in name and new not in name:
            target = name.replace(old, new)
            op.execute(sa.text(
                f'ALTER TABLE "{TABLE}" RENAME CONSTRAINT "{name}" TO "{target}"'
            ))


def _recreate_sqlite_index(bind, old: str, new: str) -> None:
    """SQLite 不支持重命名索引：删除旧唯一索引并按新列名重建。"""
    if bind.dialect.name == "postgresql":
        return
    inspector = sa.inspect(bind)
    for index in inspector.get_indexes(TABLE):
        name = index.get("name") or ""
        if index.get("column_names") == [old]:
            op.drop_index(name, table_name=TABLE)
    unique_exists = any(
        item.get("unique") and (item.get("column_names") or []) == [new]
        for item in sa.inspect(bind).get_indexes(TABLE)
    )
    if not unique_exists:
        op.create_index(f"uq_{TABLE}_{new}", TABLE, [new], unique=True)


def upgrade() -> None:
    bind = op.get_bind()
    columns = _column_names(bind)
    if NEW in columns:
        return
    if OLD not in columns:
        raise RuntimeError(
            f"{TABLE} 既不存在 {OLD} 也不存在 {NEW}，数据库结构异常，请先执行 0012。"
        )
    op.alter_column(TABLE, OLD, new_column_name=NEW)
    _rename_pg_objects(bind, OLD, NEW)
    _recreate_sqlite_index(bind, OLD, NEW)


def downgrade() -> None:
    bind = op.get_bind()
    columns = _column_names(bind)
    if OLD in columns:
        return
    if NEW not in columns:
        raise RuntimeError(
            f"{TABLE} 既不存在 {NEW} 也不存在 {OLD}，无法回滚列名。"
        )
    op.alter_column(TABLE, NEW, new_column_name=OLD)
    _rename_pg_objects(bind, NEW, OLD)
    _recreate_sqlite_index(bind, NEW, OLD)
