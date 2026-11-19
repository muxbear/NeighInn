"""0008_help_service_review_media — 邻里服务审核与互助媒体字段。

- 移动端发布邻里服务进入待审核，需后台通过后展示；邻里求助仍直接发布。
- 求助/服务支持图片与短视频，后台需可编辑媒体，补齐对象键列。

revision: 0008_help_service_review_media
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0008_help_service_review_media"
down_revision = "0007_life_manage_permissions"
branch_labels = None
depends_on = None

PERMISSIONS = (
    ("community:help:update", "编辑互助"),
    ("community:help:delete", "删除互助"),
    ("community:help:review", "审核邻里服务"),
)
ROLE_CODES = ("community_operator", "content_reviewer")


def _fresh_schema(bind) -> bool:
    """0001 按当前 metadata 建表时，账号表已直接是 platform_users。"""
    tables = set(sa.inspect(bind).get_table_names())
    return "platform_users" in tables and "users" not in tables


def upgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"
    media_type = postgresql.JSONB() if is_pg else sa.JSON()
    default = sa.text("'[]'::jsonb") if is_pg else sa.text("'[]'")
    if not _fresh_schema(bind):
        op.add_column("help_requests", sa.Column("media", media_type, nullable=False,
                                                 server_default=default))
        op.add_column("help_requests", sa.Column("cover_key", sa.String(255), nullable=False,
                                                 server_default=""))
        op.add_column("help_requests", sa.Column("media_type", sa.String(16), nullable=False,
                                                 server_default="GALLERY"))

    for code, name in PERMISSIONS:
        op.execute(
            f"""
            INSERT INTO permissions (name, code, type, route, sort, status, created_at, updated_at)
            SELECT '{name}', '{code}', '按钮', '', 0, 'ACTIVE', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            WHERE NOT EXISTS (SELECT 1 FROM permissions WHERE code = '{code}')
            """
        )
    codes_sql = "('community:help:update', 'community:help:delete', 'community:help:review')"
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
            WHERE code IN ('community:help:update', 'community:help:delete',
                           'community:help:review')
        )
        """
    )
    op.execute(
        "DELETE FROM permissions WHERE code IN "
        "('community:help:update', 'community:help:delete', 'community:help:review')"
    )
    if not _fresh_schema(op.get_bind()):
        op.drop_column("help_requests", "media_type")
        op.drop_column("help_requests", "cover_key")
        op.drop_column("help_requests", "media")
