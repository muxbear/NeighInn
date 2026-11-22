"""0016_admin_region_grants — 后台账号的区划级社区管理范围。

新增 ``admin_user_region_grants``：保存“整个区划”授权（省/市/区县/街道）。
指定社区继续使用 ``admin_user_communities``；两者在数据范围解析时取并集，
区划下后续新增社区自动纳入账号可见范围。

新库由 0001 按当前 metadata 建表；本迁移服务存量库，DDL 可重复执行。

revision: 0016_admin_region_grants
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0016_admin_region_grants"
down_revision = "0015_backfill_admin_communities"
branch_labels = None
depends_on = None

TABLE = "admin_user_region_grants"


def _table_exists(bind) -> bool:
    return TABLE in set(sa.inspect(bind).get_table_names())


def _index_exists(bind, name: str) -> bool:
    return any(item["name"] == name for item in sa.inspect(bind).get_indexes(TABLE))


def upgrade() -> None:
    bind = op.get_bind()
    if not _table_exists(bind):
        op.create_table(
            TABLE,
            sa.Column(
                "id",
                sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
                primary_key=True,
                autoincrement=True,
                nullable=False,
            ),
            sa.Column("admin_user_id", sa.BigInteger(), nullable=False),
            sa.Column("region_id", sa.BigInteger(), nullable=False),
            sa.Column(
                "created_at", sa.DateTime(timezone=True),
                nullable=False, server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.Column(
                "updated_at", sa.DateTime(timezone=True),
                nullable=False, server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.ForeignKeyConstraint(
                ["admin_user_id"], ["admin_users.id"],
                name="fk_admin_user_region_grants_admin_user_id",
            ),
            sa.ForeignKeyConstraint(
                ["region_id"], ["regions.id"],
                name="fk_admin_user_region_grants_region_id",
            ),
            sa.UniqueConstraint(
                "admin_user_id", "region_id",
                name="uq_admin_user_region_grants_admin_region",
            ),
        )
    if not _index_exists(bind, "ix_admin_user_region_grants_admin_user_id"):
        op.create_index(
            "ix_admin_user_region_grants_admin_user_id", TABLE, ["admin_user_id"])
    if not _index_exists(bind, "ix_admin_user_region_grants_region_id"):
        op.create_index(
            "ix_admin_user_region_grants_region_id", TABLE, ["region_id"])


def downgrade() -> None:
    bind = op.get_bind()
    if not _table_exists(bind):
        return
    for name in (
        "ix_admin_user_region_grants_region_id",
        "ix_admin_user_region_grants_admin_user_id",
    ):
        if _index_exists(bind, name):
            op.drop_index(name, table_name=TABLE)
    op.drop_table(TABLE)
