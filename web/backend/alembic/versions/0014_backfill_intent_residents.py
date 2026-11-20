"""0014_backfill_intent_residents — 为已注册用户补建未认证住户档案。

注册完成时已把所选入住小区写入 ``platform_users.intent_community_id``，
但早期版本不会写 ``residents``，导致后台「社区业主」按小区查不到刚注册的
用户。本迁移为「有意向小区、但该小区下没有住户档案」的平台账号补建
``certification_status=UNVERIFIED`` 的档案；已认证/审核中的档案不受影响。

档案不授予任何住户权限：发布、交易、好友、后台授权仍要求 ``VERIFIED``。

revision: 0014_backfill_intent_residents
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0014_backfill_intent_residents"
down_revision = "0013_admin_platform_user_id"
branch_labels = None
depends_on = None


def _text(value: str) -> sa.ColumnElement[str]:
    return sa.literal(value, type_=sa.String())


def upgrade() -> None:
    bind = op.get_bind()
    metadata = sa.MetaData()
    users = sa.Table("platform_users", metadata, autoload_with=bind)
    residents = sa.Table("residents", metadata, autoload_with=bind)
    communities = sa.Table("communities", metadata, autoload_with=bind)

    # 已有任意住户档案的账号不重复建档（含已认证或后台代建档）。
    has_resident = sa.select(residents.c.id).where(
        residents.c.user_id == users.c.id).exists()

    source = sa.select(
        users.c.id.label("user_id"),
        users.c.intent_community_id.label("community_id"),
        sa.func.coalesce(sa.func.nullif(users.c.nickname, ""), "邻居").label("name"),
        _text("").label("gender"),
        users.c.phone_enc.label("phone_enc"),
        users.c.phone_hash.label("phone_hash"),
        _text("业主").label("identity_type"),
        _text("").label("building"),
        _text("").label("relationship"),
        _text("UNVERIFIED").label("certification_status"),
        _text("").label("certification_no"),
        _text("普通用户").label("level"),
        _text("ACTIVE").label("status"),
        users.c.registered_at.label("joined_at"),
        sa.literal(0, type_=sa.Integer()).label("version"),
        sa.func.now().label("created_at"),
        sa.func.now().label("updated_at"),
    ).where(
        users.c.intent_community_id.is_not(None),
        sa.exists().where(communities.c.id == users.c.intent_community_id),
        ~has_resident,
    )

    columns = [
        "user_id", "community_id", "name", "gender", "phone_enc", "phone_hash",
        "identity_type", "building", "relationship", "certification_status",
        "certification_no", "level", "status", "joined_at", "version",
        "created_at", "updated_at",
    ]
    bind.execute(residents.insert().from_select(columns, source))


def downgrade() -> None:
    # 数据回填不可逆：档案创建后可能已被认证或由管理员编辑，删除会丢业务数据。
    pass
