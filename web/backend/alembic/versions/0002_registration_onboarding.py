"""0002_registration_onboarding — 用户注册引导、协议留痕与协议版本参数。

- users.onboarding_status：NEW / PROFILE_COMPLETED / COMPLETED。
  采用 server_default='COMPLETED'，存量用户迁移后不会被强制拉去注册；
  新建用户由 auth_service.get_or_create_user_by_phone 显式写 NEW。
- users.intent_community_id：注册时选择的意向小区，仅用于内容推荐；
  业主证明通过后才写 residents 正式绑定。
- users.registration_channel / agreement_version / privacy_version / agreed_at：
  注册渠道与协议同意留痕。
- 参数 keys：协议版本由管理员在后台参数配置维护。

注意：0001_initial 使用当前 metadata 全量建表，因此在全新数据库上本迁移的
DDL 需要先做存在性判断，避免重复加列；存量数据库则正常增量执行。

revision: 0002_registration_onboarding
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0002_registration_onboarding"
down_revision = "0001_initial"
branch_labels = None
depends_on = None

AGREEMENT_PARAMS = [
    ("agreement.user.version", "2026-11-01", "用户协议版本（管理员维护）"),
    ("agreement.privacy.version", "2026-11-01", "隐私政策版本（管理员维护）"),
]


def _fresh_schema(bind) -> bool:
    """0001 按当前 metadata 建表时，账号表已直接是 platform_users。"""
    tables = set(sa.inspect(bind).get_table_names())
    return "platform_users" in tables and "users" not in tables


def _column_names(bind) -> set[str]:
    return {column["name"] for column in sa.inspect(bind).get_columns("users")}


def _index_names(bind) -> set[str]:
    return {index["name"] for index in sa.inspect(bind).get_indexes("users")}


def _has_intent_fk(bind) -> bool:
    for fk in sa.inspect(bind).get_foreign_keys("users"):
        if fk.get("constrained_columns") == ["intent_community_id"]:
            return True
    return False


def _ensure_agreement_parameters(bind) -> None:
    metadata = sa.MetaData()
    keys = sa.Table("parameter_keys", metadata, autoload_with=bind)
    items = sa.Table("parameter_items", metadata, autoload_with=bind)

    group_code = "group.5"
    group_row = bind.execute(
        sa.select(keys.c.id).where(keys.c.code == group_code)
    ).first()
    if group_row:
        group_id = group_row[0]
    else:
        result = bind.execute(keys.insert().values(
            label="账号与合规", code=group_code, kind="GROUP", sort=5, status="启用",
        ))
        group_id = result.inserted_primary_key[0]

    for sort, (code, value, description) in enumerate(AGREEMENT_PARAMS):
        exists = bind.execute(sa.select(keys.c.id).where(keys.c.code == code)).first()
        if exists:
            continue
        result = bind.execute(keys.insert().values(
            parent_id=group_id,
            label=description[:12],
            code=code,
            kind="KEY",
            sort=sort,
            status="启用",
        ))
        key_id = result.inserted_primary_key[0]
        bind.execute(items.insert().values(
            parameter_key_id=key_id,
            name=code,
            value=value,
            description=description,
            status="启用",
            version=0,
            created_at=sa.func.now(),
            updated_at=sa.func.now(),
        ))


def upgrade() -> None:
    bind = op.get_bind()
    if _fresh_schema(bind):
        # 新库的注册引导字段已由 0001 按当前模型创建，只需补齐协议参数。
        _ensure_agreement_parameters(bind)
        return

    columns = _column_names(bind)
    if "onboarding_status" not in columns:
        op.add_column(
            "users",
            sa.Column("onboarding_status", sa.String(length=16), nullable=False,
                      server_default="COMPLETED"),
        )
    if "intent_community_id" not in columns:
        op.add_column("users", sa.Column("intent_community_id", sa.BigInteger(), nullable=True))
    if "registration_channel" not in columns:
        op.add_column(
            "users",
            sa.Column("registration_channel", sa.String(length=16), nullable=False,
                      server_default="sms"),
        )
    if "agreement_version" not in columns:
        op.add_column(
            "users",
            sa.Column("agreement_version", sa.String(length=32), nullable=False,
                      server_default=""),
        )
    if "privacy_version" not in columns:
        op.add_column(
            "users",
            sa.Column("privacy_version", sa.String(length=32), nullable=False,
                      server_default=""),
        )
    if "agreed_at" not in columns:
        op.add_column("users", sa.Column("agreed_at", sa.DateTime(timezone=True), nullable=True))

    indexes = _index_names(bind)
    if "ix_users_onboarding_status" not in indexes:
        op.create_index("ix_users_onboarding_status", "users", ["onboarding_status"])
    if "ix_users_intent_community_id" not in indexes:
        op.create_index("ix_users_intent_community_id", "users", ["intent_community_id"])
    if not _has_intent_fk(bind):
        op.create_foreign_key(
            "fk_users_intent_community", "users", "communities",
            ["intent_community_id"], ["id"],
        )

    _ensure_agreement_parameters(bind)


def downgrade() -> None:
    bind = op.get_bind()
    if _fresh_schema(bind):
        return

    metadata = sa.MetaData()
    keys = sa.Table("parameter_keys", metadata, autoload_with=bind)
    items = sa.Table("parameter_items", metadata, autoload_with=bind)
    codes = [code for code, _, _ in AGREEMENT_PARAMS]
    bind.execute(items.delete().where(items.c.name.in_(codes)))
    bind.execute(keys.delete().where(keys.c.code.in_(codes)))

    indexes = _index_names(bind)
    if "ix_users_intent_community_id" in indexes:
        op.drop_index("ix_users_intent_community_id", table_name="users")
    if "ix_users_onboarding_status" in indexes:
        op.drop_index("ix_users_onboarding_status", table_name="users")
    if _has_intent_fk(bind):
        op.drop_constraint("fk_users_intent_community", "users", type_="foreignkey")

    columns = _column_names(bind)
    for column in ("agreed_at", "privacy_version", "agreement_version",
                   "registration_channel", "intent_community_id", "onboarding_status"):
        if column in columns:
            op.drop_column("users", column)
