"""0001_initial — 统一领域模型初始建表。

初始迁移按 metadata 全量建表（Phase 0 无生产数据，允许按目标模型重建）。
此后的所有变更必须走增量迁移：

    uv run alembic revision --autogenerate -m "描述"
    uv run alembic upgrade head

revision: 0001_initial
"""

from __future__ import annotations

from alembic import op
from src.db import models  # noqa: F401
from src.db.base import Base

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
