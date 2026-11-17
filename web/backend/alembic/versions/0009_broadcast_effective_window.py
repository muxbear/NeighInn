"""0009_broadcast_effective_window — 社区喇叭生效时间窗与编辑/删除权限。

- 喇叭发布后直接生效，支持即时或指定时间段；
- `expires_at` 记录失效时间，未配置时由 API 默认 24 小时；
- 补齐后台编辑/删除喇叭权限。

revision: 0009_broadcast_effective_window
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0009_broadcast_effective_window"
down_revision = "0008_help_service_review_media"
branch_labels = None
depends_on = None

PERMISSIONS = (
    ("community:broadcast:update", "编辑喇叭"),
    ("community:broadcast:delete", "删除喇叭"),
)
ROLE_CODES = ("community_operator", "content_reviewer")


def upgrade() -> None:
    op.add_column("broadcasts", sa.Column("expires_at", sa.DateTime(timezone=True),
                                          nullable=True))

    for code, name in PERMISSIONS:
        op.execute(
            f"""
            INSERT INTO permissions (name, code, type, route, sort, status, created_at, updated_at)
            SELECT '{name}', '{code}', '按钮', '', 0, 'ACTIVE', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            WHERE NOT EXISTS (SELECT 1 FROM permissions WHERE code = '{code}')
            """
        )
    codes_sql = "('community:broadcast:update', 'community:broadcast:delete')"
    for role_code in ROLE_CODES:
        op.execute(
            f"""
            INSERT INTO role_permissions (role_id, permission_id)
            SELECT r.id, p.id
            FROM roles r, permissions p
            WHERE r.code = '{role_code}'
              AND p.code IN {codes_sql}
              AND NOT EXISTS (
                  SELECT 1 FROM role_permissions rp
                  WHERE rp.role_id = r.id AND rp.permission_id = p.id
              )
            """
        )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM role_permissions
        WHERE permission_id IN (
            SELECT id FROM permissions
            WHERE code IN ('community:broadcast:update', 'community:broadcast:delete')
        )
        """
    )
    op.execute(
        "DELETE FROM permissions WHERE code IN "
        "('community:broadcast:update', 'community:broadcast:delete')"
    )
    op.drop_column("broadcasts", "expires_at")
