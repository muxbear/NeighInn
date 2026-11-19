"""0006_widen_onboarding_status — 修正 users.onboarding_status 列宽。

状态值 PROFILE_COMPLETED 长 17，原列宽 varchar(16) 在 PostgreSQL 写入时抛
StringDataRightTruncation，导致「完成注册」接口 500。放宽到 32，与其它状态列一致。
SQLite 不校验 varchar 长度，无需变更。

revision: 0006_widen_onboarding_status
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0006_widen_onboarding_status"
down_revision = "0005_item_manage_permissions"
branch_labels = None
depends_on = None


def _fresh_schema(bind) -> bool:
    """0001 按当前 metadata 建表时，账号表已直接是 platform_users。"""
    tables = set(sa.inspect(bind).get_table_names())
    return "platform_users" in tables and "users" not in tables


def upgrade() -> None:
    bind = op.get_bind()
    if _fresh_schema(bind):
        return
    if bind.dialect.name != "postgresql":
        return
    op.alter_column(
        "users",
        "onboarding_status",
        existing_type=sa.String(length=16),
        type_=sa.String(length=32),
        existing_nullable=False,
        existing_server_default="COMPLETED",
    )


def downgrade() -> None:
    bind = op.get_bind()
    if _fresh_schema(bind):
        return
    if bind.dialect.name != "postgresql":
        return
    # 若库中已存在 PROFILE_COMPLETED（17 字符），回退会因超长失败；
    # 该列宽变更为修复性迁移，生产环境不建议回退。
    op.alter_column(
        "users",
        "onboarding_status",
        existing_type=sa.String(length=32),
        type_=sa.String(length=16),
        existing_nullable=False,
        existing_server_default="COMPLETED",
    )
