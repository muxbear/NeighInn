"""0004_user_profile_fields — 用户资料补充邮箱与个人描述。

移动端 UserProfile 契约包含 email / bio（M07-06），后台业主档案需按独立字段展示。
存量用户回填空字符串。

revision: 0004_user_profile_fields
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0004_user_profile_fields"
down_revision = "0003_cert_pending_unique"
branch_labels = None
depends_on = None


def _fresh_schema(bind) -> bool:
    """0001 按当前 metadata 建表时，账号表已直接是 platform_users。"""
    tables = set(sa.inspect(bind).get_table_names())
    return "platform_users" in tables and "users" not in tables


def _column_exists(bind, table: str, column: str) -> bool:
    return any(col["name"] == column for col in sa.inspect(bind).get_columns(table))


def upgrade() -> None:
    bind = op.get_bind()
    if _fresh_schema(bind):
        return
    if not _column_exists(bind, "users", "email"):
        op.add_column(
            "users",
            sa.Column("email", sa.String(length=128), nullable=False, server_default=""),
        )
    if not _column_exists(bind, "users", "bio"):
        op.add_column(
            "users",
            sa.Column("bio", sa.Text(), nullable=False, server_default=""),
        )


def downgrade() -> None:
    bind = op.get_bind()
    if _fresh_schema(bind):
        return
    if _column_exists(bind, "users", "bio"):
        op.drop_column("users", "bio")
    if _column_exists(bind, "users", "email"):
        op.drop_column("users", "email")
