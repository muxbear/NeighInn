"""0007_life_manage_permissions — 社区生活编辑/删除权限。

后台新增生活内容编辑与删除操作，需要在存量库补齐权限码并授权给已有内容运营角色。
新库由 seed 直接写入，无需重复执行本迁移的数据。

revision: 0007_life_manage_permissions
"""

from __future__ import annotations

from alembic import op

revision = "0007_life_manage_permissions"
down_revision = "0006_widen_onboarding_status"
branch_labels = None
depends_on = None

PERMISSIONS = (
    ("community:life:update", "编辑生活内容"),
    ("community:life:delete", "删除生活内容"),
)
ROLE_CODES = ("community_operator", "content_reviewer")


def upgrade() -> None:
    for code, name in PERMISSIONS:
        op.execute(
            f"""
            INSERT INTO permissions (name, code, type, route, sort, status, created_at, updated_at)
            SELECT '{name}', '{code}', '按钮', '', 0, 'ACTIVE', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            WHERE NOT EXISTS (SELECT 1 FROM permissions WHERE code = '{code}')
            """
        )
    for role_code in ROLE_CODES:
        op.execute(
            f"""
            INSERT INTO role_permissions (role_id, permission_id)
            SELECT r.id, p.id
            FROM roles r, permissions p
            WHERE r.code = '{role_code}'
              AND p.code IN ('community:life:update', 'community:life:delete')
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
            WHERE code IN ('community:life:update', 'community:life:delete')
        )
        """
    )
    op.execute(
        "DELETE FROM permissions WHERE code IN "
        "('community:life:update', 'community:life:delete')"
    )
