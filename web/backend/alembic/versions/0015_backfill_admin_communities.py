"""0015_backfill_admin_communities — 为已关联住户的后台账号补齐社区数据范围。

用户管理表单已不再单独维护「可访问社区」，手工创建的账号若只关联住户而
``admin_user_communities`` 为空，其「社区管理员」等 OWN_COMMUNITY 角色会因
数据范围为空而查不到任何小区（「社区业主」页按行政区划检索小区无结果）。
本迁移为「已关联住户、且尚未配置任何可访问社区」的后台账号补入住户所在
社区；已配置社区的账号保持原样。

revision: 0015_backfill_resident_admin_communities
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0015_backfill_admin_communities"
down_revision = "0014_backfill_intent_residents"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    metadata = sa.MetaData()
    admins = sa.Table("admin_users", metadata, autoload_with=bind)
    residents = sa.Table("residents", metadata, autoload_with=bind)
    communities = sa.Table("communities", metadata, autoload_with=bind)
    admin_communities = sa.Table("admin_user_communities", metadata, autoload_with=bind)
    admin_roles = sa.Table("admin_user_roles", metadata, autoload_with=bind)
    roles = sa.Table("roles", metadata, autoload_with=bind)

    has_scope = sa.select(admin_communities.c.admin_user_id).where(
        admin_communities.c.admin_user_id == admins.c.id).exists()
    # 仅非 ALL 数据范围的角色需要社区集合；纯 ALL 账号不写入冗余行。
    needs_scope = sa.select(admin_roles.c.admin_user_id).join(
        roles, roles.c.id == admin_roles.c.role_id,
    ).where(
        admin_roles.c.admin_user_id == admins.c.id,
        roles.c.data_scope != "ALL",
    ).exists()
    community_exists = sa.select(communities.c.id).where(
        communities.c.id == residents.c.community_id).exists()

    source = sa.select(
        admins.c.id.label("admin_user_id"),
        residents.c.community_id.label("community_id"),
    ).join(
        residents, residents.c.id == admins.c.resident_id,
    ).where(
        admins.c.resident_id.is_not(None),
        community_exists,
        needs_scope,
        ~has_scope,
    )

    bind.execute(admin_communities.insert().from_select(
        ["admin_user_id", "community_id"], source))


def downgrade() -> None:
    # 数据回填不可逆：后续可能已在同一社区上配置角色与业务数据。
    pass
