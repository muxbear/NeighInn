"""校验 0012_resident_admin_link 迁移结果（只读）。

用法：``PYTHONIOENCODING=utf-8 uv run python scripts/verify_resident_admin_migration.py``
检查 admin_users 新字段、社区管理员角色、授权权限码与新增索引是否就绪。
"""

import asyncio

from sqlalchemy import text

from src.db.base import engine


async def main() -> None:
    async with engine.connect() as conn:
        roles = (await conn.execute(text(
            "SELECT code, assignable_to_resident FROM roles "
            "WHERE code IN ('community_admin', 'community_operator') ORDER BY code"
        ))).all()
        print("roles:", roles)
        cols = (await conn.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'admin_users' "
            "AND column_name IN ('platform_user_id', 'resident_id', 'source', "
            "'must_change_password', 'session_version') ORDER BY column_name"
        ))).scalars().all()
        print("admin_users columns:", cols)
        perms = (await conn.execute(text(
            "SELECT code FROM permissions "
            "WHERE code LIKE 'community:resident:admin-%' ORDER BY code"
        ))).scalars().all()
        print("permissions:", perms)
        role_perms = (await conn.execute(text(
            "SELECT r.code, p.code FROM roles r "
            "JOIN role_permissions rp ON rp.role_id = r.id "
            "JOIN permissions p ON p.id = rp.permission_id "
            "WHERE r.code = 'community_admin' "
            "AND p.code LIKE 'community:resident:%' ORDER BY p.code"
        ))).all()
        print("community_admin resident perms:", role_perms)
        indexes = (await conn.execute(text(
            "SELECT indexname FROM pg_indexes "
            "WHERE tablename IN ('admin_users', 'residents') "
            "AND (indexname LIKE 'uq_admin_users%' OR indexname LIKE 'uq_residents%' "
            "OR indexname LIKE 'ix_residents_community%') ORDER BY indexname"
        ))).scalars().all()
        print("indexes:", indexes)
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
