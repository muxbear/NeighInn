"""0003_cert_pending_unique — 防止同一用户同类型重复待审认证单。

同一用户同一认证类型只允许存在一条 PENDING / SUPPLEMENT 认证单，
避免双击提交或多端并发产生重复「住户认证」待办。

revision: 0003_cert_pending_unique
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0003_cert_pending_unique"
down_revision = "0002_registration_onboarding"
branch_labels = None
depends_on = None

INDEX_NAME = "uq_certifications_pending_user_type"
WHERE_SQL = "status IN ('PENDING', 'SUPPLEMENT')"


def _index_exists(bind) -> bool:
    return any(
        index["name"] == INDEX_NAME
        for index in sa.inspect(bind).get_indexes("certifications")
    )


def upgrade() -> None:
    bind = op.get_bind()
    if _index_exists(bind):
        return
    op.create_index(
        INDEX_NAME,
        "certifications",
        ["user_id", "type"],
        unique=True,
        postgresql_where=sa.text(WHERE_SQL),
        sqlite_where=sa.text(WHERE_SQL),
    )


def downgrade() -> None:
    bind = op.get_bind()
    if _index_exists(bind):
        op.drop_index(INDEX_NAME, table_name="certifications")
