"""0012_resident_admin_link — 住户与后台账号关联、社区管理员角色。

- admin_users 关联 platform_users / residents，记录来源、强制改密与会话版本；
- roles 新增 assignable_to_resident；
- 住户档案增加 (community_id, user_id) 部分唯一索引与列表组合索引；
- 补充住户后台授权/解除权限与内置「社区管理员」角色。

新库由 seed / Base.metadata 直接建出；本迁移服务存量库，所有 DDL 均可重复执行。

revision: 0012_resident_admin_link
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0012_resident_admin_link"
down_revision = "0011_rename_users_table"
branch_labels = None
depends_on = None

ADMIN_USER_COLUMNS = (
    sa.Column("user_id", sa.BigInteger(), nullable=True),
    sa.Column("resident_id", sa.BigInteger(), nullable=True),
    sa.Column("source", sa.String(length=16), nullable=False, server_default=sa.text("'MANUAL'")),
    sa.Column("must_change_password", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    sa.Column("session_version", sa.Integer(), nullable=False, server_default=sa.text("0")),
)

NEW_PERMISSIONS = (
    ("community:resident:admin-grant", "授予住户后台角色"),
    ("community:resident:admin-revoke", "解除住户后台授权"),
)

COMMUNITY_ADMIN_PERMISSIONS = (
    "dashboard:view",
    "community:broadcast:view", "community:broadcast:create",
    "community:broadcast:update", "community:broadcast:delete",
    "community:broadcast:review", "community:broadcast:offline",
    "community:item:view", "community:item:create", "community:item:update",
    "community:item:delete", "community:item:review", "community:item:recommend",
    "community:item:offline",
    "community:help:view", "community:help:create", "community:help:update",
    "community:help:delete", "community:help:review", "community:help:match",
    "community:help:close",
    "community:life:view", "community:life:create", "community:life:update",
    "community:life:delete", "community:life:review", "community:life:offline",
    "community:maintenance:view",
    "community:resident:view", "community:resident:audit",
    "communication:notice:view", "communication:notice:create",
    "communication:notice:publish",
    "communication:task:view", "communication:task:create", "communication:task:send",
    "governance:report:view", "governance:report:handle",
    "reporting:export:view",
)

RESIDENT_INDEXES = (
    ("ix_residents_community_identity", ("community_id", "identity_type")),
    ("ix_residents_community_cert", ("community_id", "certification_status")),
    ("ix_residents_community_status", ("community_id", "status")),
)


def _column_exists(bind, table: str, column: str) -> bool:
    return any(item["name"] == column for item in sa.inspect(bind).get_columns(table))


def _index_exists(bind, table: str, name: str) -> bool:
    return any(item["name"] == name for item in sa.inspect(bind).get_indexes(table))


def _fk_exists(bind, table: str, column: str) -> bool:
    """按列判断外键是否存在，兼容 create_all 生成的默认约束名。"""
    return any(
        column in (item.get("constrained_columns") or [])
        for item in sa.inspect(bind).get_foreign_keys(table)
    )


def _unique_index_on(bind, table: str, column: str) -> bool:
    return any(
        item.get("unique") and (item.get("column_names") or []) == [column]
        for item in sa.inspect(bind).get_indexes(table)
    )


def _ensure_admin_user_columns(bind) -> None:
    for column in ADMIN_USER_COLUMNS:
        if not _column_exists(bind, "admin_users", column.name):
            op.add_column("admin_users", column)
    # SQLite 不支持在已有表上追加外键；测试库由 create_all 按模型建表。
    if bind.dialect.name == "postgresql":
        if not _fk_exists(bind, "admin_users", "user_id"):
            op.create_foreign_key(
                "fk_admin_users_user_id", "admin_users", "platform_users", ["user_id"], ["id"]
            )
        if not _fk_exists(bind, "admin_users", "resident_id"):
            op.create_foreign_key(
                "fk_admin_users_resident_id", "admin_users", "residents", ["resident_id"], ["id"]
            )
    if not _unique_index_on(bind, "admin_users", "user_id"):
        op.create_index("uq_admin_users_user_id", "admin_users", ["user_id"], unique=True)
    if not _index_exists(bind, "admin_users", "ix_admin_users_resident_id"):
        op.create_index("ix_admin_users_resident_id", "admin_users", ["resident_id"])
    if not _index_exists(bind, "admin_users", "ix_admin_users_source"):
        op.create_index("ix_admin_users_source", "admin_users", ["source"])


def _ensure_role_column(bind) -> None:
    if not _column_exists(bind, "roles", "assignable_to_resident"):
        op.add_column(
            "roles",
            sa.Column(
                "assignable_to_resident",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
        )


def _ensure_join_indexes(bind) -> None:
    if not _index_exists(bind, "admin_user_roles", "ix_admin_user_roles_role_id"):
        op.create_index("ix_admin_user_roles_role_id", "admin_user_roles", ["role_id"])
    if not _index_exists(bind, "admin_user_communities", "ix_admin_user_communities_community_id"):
        op.create_index(
            "ix_admin_user_communities_community_id",
            "admin_user_communities",
            ["community_id"],
        )


def _ensure_resident_indexes(bind) -> None:
    duplicates = bind.execute(sa.text(
        """
        SELECT community_id, user_id, count(*) AS duplicate_count
        FROM residents
        WHERE user_id IS NOT NULL
        GROUP BY community_id, user_id
        HAVING count(*) > 1
        """
    )).all()
    if duplicates:
        detail = ", ".join(
            f"(community_id={row[0]}, user_id={row[1]}, count={row[2]})"
            for row in duplicates
        )
        raise RuntimeError(
            "residents 存在同一社区同一账号的重复档案，无法创建唯一索引："
            f"{detail}。请先人工合并重复档案。"
        )
    if not _index_exists(bind, "residents", "uq_residents_community_user"):
        op.create_index(
            "uq_residents_community_user",
            "residents",
            ["community_id", "user_id"],
            unique=True,
            postgresql_where=sa.text("user_id IS NOT NULL"),
            sqlite_where=sa.text("user_id IS NOT NULL"),
        )
    for name, columns in RESIDENT_INDEXES:
        if not _index_exists(bind, "residents", name):
            op.create_index(name, "residents", list(columns))


def _ensure_permissions_and_role(bind) -> None:
    for code, name in NEW_PERMISSIONS:
        # 显式 CAST：同一参数在 SELECT 与子查询中出现两次，PostgreSQL 无法统一推断类型。
        bind.execute(sa.text(
            """
            INSERT INTO permissions (name, code, type, route, sort, status, created_at, updated_at)
            SELECT CAST(:name AS VARCHAR(64)), CAST(:code AS VARCHAR(128)),
                   '按钮', '', 0, 'ACTIVE', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            WHERE NOT EXISTS (
                SELECT 1 FROM permissions WHERE code = CAST(:code AS VARCHAR(128))
            )
            """
        ), {"name": name, "code": code})

    # 社区运营默认可授予/解除住户后台角色。
    bind.execute(sa.text(
        """
        INSERT INTO role_permissions (role_id, permission_id)
        SELECT r.id, p.id
        FROM roles r, permissions p
        WHERE r.code = 'community_operator'
          AND p.code IN ('community:resident:admin-grant', 'community:resident:admin-revoke')
          AND NOT EXISTS (
              SELECT 1 FROM role_permissions rp
              WHERE rp.role_id = r.id AND rp.permission_id = p.id
          )
        """
    ))

    bind.execute(sa.text(
        """
        INSERT INTO roles (
            name, code, description, is_builtin, data_scope,
            assignable_to_resident, status, version, created_at, updated_at
        )
        SELECT '社区管理员', 'community_admin',
               '负责本社区内容运营、住户服务与认证审核',
               true, 'OWN_COMMUNITY', true, 'ACTIVE', 0,
               CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
        WHERE NOT EXISTS (SELECT 1 FROM roles WHERE code = 'community_admin')
        """
    ))
    bind.execute(sa.text(
        """
        UPDATE roles
        SET assignable_to_resident = true
        WHERE code = 'community_admin'
        """
    ))

    placeholders = ", ".join(f":p{i}" for i in range(len(COMMUNITY_ADMIN_PERMISSIONS)))
    bind.execute(sa.text(
        f"""
        INSERT INTO role_permissions (role_id, permission_id)
        SELECT r.id, p.id
        FROM roles r, permissions p
        WHERE r.code = 'community_admin'
          AND p.code IN ({placeholders})
          AND NOT EXISTS (
              SELECT 1 FROM role_permissions rp
              WHERE rp.role_id = r.id AND rp.permission_id = p.id
          )
        """
    ), {f"p{i}": code for i, code in enumerate(COMMUNITY_ADMIN_PERMISSIONS)})


def upgrade() -> None:
    bind = op.get_bind()
    _ensure_admin_user_columns(bind)
    _ensure_role_column(bind)
    _ensure_join_indexes(bind)
    _ensure_resident_indexes(bind)
    _ensure_permissions_and_role(bind)


def downgrade() -> None:
    bind = op.get_bind()
    members = bind.execute(sa.text(
        """
        SELECT count(*)
        FROM admin_user_roles r
        JOIN roles ro ON ro.id = r.role_id
        WHERE ro.code = 'community_admin'
        """
    )).scalar()
    if members:
        raise RuntimeError("community_admin 角色仍有成员，请先移除成员再回滚 0012。")

    bind.execute(sa.text(
        """
        DELETE FROM role_permissions
        WHERE role_id IN (SELECT id FROM roles WHERE code = 'community_admin')
        """
    ))
    bind.execute(sa.text("DELETE FROM roles WHERE code = 'community_admin'"))
    bind.execute(sa.text(
        """
        DELETE FROM role_permissions
        WHERE permission_id IN (
            SELECT id FROM permissions
            WHERE code IN ('community:resident:admin-grant', 'community:resident:admin-revoke')
        )
        """
    ))
    bind.execute(sa.text(
        "DELETE FROM permissions WHERE code IN "
        "('community:resident:admin-grant', 'community:resident:admin-revoke')"
    ))

    if _index_exists(bind, "residents", "uq_residents_community_user"):
        op.drop_index("uq_residents_community_user", table_name="residents")
    for name, _columns in RESIDENT_INDEXES:
        if _index_exists(bind, "residents", name):
            op.drop_index(name, table_name="residents")

    for name in ("ix_admin_user_roles_role_id",):
        if _index_exists(bind, "admin_user_roles", name):
            op.drop_index(name, table_name="admin_user_roles")
    if _index_exists(bind, "admin_user_communities", "ix_admin_user_communities_community_id"):
        op.drop_index("ix_admin_user_communities_community_id",
                      table_name="admin_user_communities")

    for name in ("ix_admin_users_source", "ix_admin_users_resident_id", "uq_admin_users_user_id"):
        if _index_exists(bind, "admin_users", name):
            op.drop_index(name, table_name="admin_users")
    if bind.dialect.name == "postgresql":
        # 仅删除本迁移显式创建的命名约束，不触碰 create_all 生成的默认约束。
        for name in ("fk_admin_users_resident_id", "fk_admin_users_user_id"):
            if any(
                item.get("name") == name
                for item in sa.inspect(bind).get_foreign_keys("admin_users")
            ):
                op.drop_constraint(name, "admin_users", type_="foreignkey")
    for column in reversed(ADMIN_USER_COLUMNS):
        if _column_exists(bind, "admin_users", column.name):
            op.drop_column("admin_users", column.name)

    if _column_exists(bind, "roles", "assignable_to_resident"):
        op.drop_column("roles", "assignable_to_resident")
