#!/usr/bin/env python
"""生成邻里小栈生产库全量初始化 SQL（DROP/CREATE DATABASE + DDL + 基线数据）。

与 Alembic head ``0013_admin_platform_user_id`` 对齐：

- DDL 直接由 SQLAlchemy 模型元数据按 PostgreSQL 方言编译，保证与代码一致；
- 基线数据取自 ``src/db/seed.py``（区划/社区/类目/字典/权限/角色/参数/热词），
  不包含任何演示业务数据（物品/订单/平台用户）；
- 初始管理员密码默认随机生成，仅输出到终端，不写入 SQL 文件；首次登录强制改密。

用法（在 web/backend 目录执行）::

    uv run python scripts/generate_prod_init_sql.py
    uv run python scripts/generate_prod_init_sql.py --admin-password 'YourStrongPwd#2026'
    uv run python scripts/generate_prod_init_sql.py --db-name neighinn_prod --out deploy/init.sql
"""

from __future__ import annotations

import argparse
import json
import secrets
import string
import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

from src.core.security import hash_password
from src.db import models  # noqa: F401  # 注册全部模型到 metadata
from src.db.base import Base
from src.db.seed import (
    COMMUNITIES,
    DICTIONARIES,
    HOT_KEYWORDS,
    ITEM_CATEGORIES,
    PARAMETER_TREE,
    PERMISSIONS,
    REGIONS,
    ROLE_BLUEPRINTS,
    ROLE_PERMISSION_PREFIXES,
)

ALEMBIC_HEAD = "0013_admin_platform_user_id"

# 迁移 0008 对存量库的补充授权：给内容审核员追加邻里服务编辑/删除/审核权限。
# seed.py 的角色前缀未覆盖这部分，这里显式补齐，保证本脚本与「迁移建库」的权限一致。
SUPPLEMENTAL_ROLE_PERMISSIONS: dict[str, tuple[str, ...]] = {
    "content_reviewer": (
        "community:help:update",
        "community:help:delete",
        "community:help:review",
    ),
}


class Raw(str):
    """直接写入 SQL 的片段（如 now()）。"""


NOW = Raw("now()")


# ---------------------------------------------------------------- SQL 值渲染


def _quote(text: str) -> str:
    """使用 E'' 字符串：反斜杠与单引号都显式转义，不依赖 standard_conforming_strings。"""
    escaped = text.replace("\\", "\\\\").replace("'", "''")
    return f"E'{escaped}'"


def sql_value(value: object) -> str:
    if isinstance(value, Raw):
        return str(value)
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, (float, Decimal)):
        return str(value)
    if isinstance(value, (dict, list)):
        return _quote(json.dumps(value, ensure_ascii=False, separators=(",", ":")))
    if isinstance(value, datetime):
        return _quote(value.isoformat(sep=" ", timespec="seconds"))
    if isinstance(value, date):
        return _quote(value.isoformat())
    return _quote(str(value))


def insert_block(table: str, rows: list[dict[str, object]], batch_size: int = 200) -> list[str]:
    """生成多行 INSERT；rows 的键顺序必须一致。"""
    if not rows:
        return []
    columns = list(rows[0].keys())
    header = f"INSERT INTO {table} ({', '.join(columns)}) VALUES"
    statements: list[str] = []
    for start in range(0, len(rows), batch_size):
        chunk = rows[start:start + batch_size]
        tuples = [
            "(" + ", ".join(sql_value(row[column]) for column in columns) + ")"
            for row in chunk
        ]
        statements.append(header + "\n    " + ",\n    ".join(tuples) + ";")
    return statements


# ---------------------------------------------------------------- DDL


def build_ddl() -> list[str]:
    dialect = postgresql.dialect()
    statements: list[str] = []
    for table in Base.metadata.sorted_tables:
        statements.append(str(CreateTable(table).compile(dialect=dialect)).strip() + ";")
    for table in Base.metadata.sorted_tables:
        for index in sorted(table.indexes, key=lambda item: item.name or ""):
            statements.append(str(CreateIndex(index).compile(dialect=dialect)).strip() + ";")
    return statements


# ---------------------------------------------------------------- 基线数据


def build_seed_data(admin_username: str, admin_password_hash: str) -> dict[str, list[dict]]:
    data: dict[str, list[dict]] = {}

    # 行政区划：显式 ID，便于回填父子关系；先编号再解析 parent_id。
    code_to_id = {item[2]: position + 1 for position, item in enumerate(REGIONS)}
    region_rows: list[dict] = []
    for position, (name, level, code, parent_code, sort) in enumerate(REGIONS):
        parent_id = code_to_id.get(parent_code) if parent_code else None
        if parent_code and parent_id is None:
            raise SystemExit(f"区划数据异常：{code} 的上级 {parent_code} 不存在")
        region_rows.append({
            "id": position + 1,
            "parent_id": parent_id,
            "level": level,
            "name": name,
            "code": code,
            "sort": sort,
        })
    data["regions"] = region_rows

    # 社区：与 seed_if_empty 一致，region_id 取街道所属区县。
    community_rows: list[dict] = []
    for position, (name, code, community_type, street_code, address,
                   longitude, latitude, households, population) in enumerate(COMMUNITIES):
        street_id = code_to_id.get(street_code)
        if street_id is None:
            raise SystemExit(f"社区 {name} 的街道编码 {street_code} 不在区划数据中")
        street = region_rows[street_id - 1]
        community_rows.append({
            "id": position + 1,
            "region_id": street["parent_id"],
            "street_id": street_id,
            "name": name,
            "code": code,
            "type": community_type,
            "address": address,
            "longitude": longitude,
            "latitude": latitude,
            "property_contact_enc": "",
            "households": households,
            "population": population,
            "manager_name": "",
            "status": "OPERATING",
            "opened_at": date(2024, 1, 1),
            "created_at": NOW,
            "updated_at": NOW,
            "version": 0,
        })
    data["communities"] = community_rows

    # 物品类目：父类目在前，子类目连续编号。
    category_rows: list[dict] = []
    next_id = 1
    for sort, (parent_name, children) in enumerate(ITEM_CATEGORIES):
        parent_id = next_id
        category_rows.append({
            "id": parent_id,
            "parent_id": None,
            "name": parent_name,
            "icon": "",
            "sort": sort,
            "status": "启用",
        })
        next_id += 1
        for child_sort, child_name in enumerate(children):
            category_rows.append({
                "id": next_id,
                "parent_id": parent_id,
                "name": child_name,
                "icon": "",
                "sort": child_sort,
                "status": "启用",
            })
            next_id += 1
    data["item_categories"] = category_rows

    # 字典及字典项。
    dictionary_rows: list[dict] = []
    dictionary_item_rows: list[dict] = []
    next_item_id = 1
    for index, (code, items) in enumerate(DICTIONARIES.items(), start=1):
        dictionary_rows.append({
            "id": index,
            "code": code,
            "name": code,
            "description": f"{code} 字典",
            "status": "启用",
        })
        for sort, (label, value, tone) in enumerate(items):
            dictionary_item_rows.append({
                "id": next_item_id,
                "dictionary_id": index,
                "label": label,
                "value": value,
                "tone": tone,
                "sort": sort,
                "status": "启用",
            })
            next_item_id += 1
    data["dictionaries"] = dictionary_rows
    data["dictionary_items"] = dictionary_item_rows

    # 权限、角色、角色权限。
    permission_rows: list[dict] = []
    permission_id_by_code: dict[str, int] = {}
    for sort, (code, name, permission_type, route) in enumerate(PERMISSIONS, start=1):
        permission_rows.append({
            "id": sort,
            "parent_id": None,
            "name": name,
            "code": code,
            "type": permission_type,
            "route": route or "",
            "sort": sort - 1,
            "status": "ACTIVE",
            "created_at": NOW,
            "updated_at": NOW,
        })
        permission_id_by_code[code] = sort
    data["permissions"] = permission_rows

    role_rows: list[dict] = []
    role_id_by_code: dict[str, int] = {}
    for index, (code, blueprint) in enumerate(ROLE_BLUEPRINTS.items(), start=1):
        role_rows.append({
            "id": index,
            "name": blueprint["name"],
            "code": code,
            "description": blueprint["description"],
            "is_builtin": blueprint.get("builtin", False),
            "data_scope": blueprint["data_scope"],
            "assignable_to_resident": blueprint.get("assignable_to_resident", False),
            "status": "ACTIVE",
            "version": 0,
            "created_at": NOW,
            "updated_at": NOW,
        })
        role_id_by_code[code] = index
    data["roles"] = role_rows

    role_permission_rows: list[dict] = []
    assigned_pairs: set[tuple[int, int]] = set()

    def grant(role_code: str, permission_code: str) -> None:
        if permission_code not in permission_id_by_code:
            raise SystemExit(f"角色 {role_code} 引用了不存在的权限 {permission_code}")
        pair = (role_id_by_code[role_code], permission_id_by_code[permission_code])
        if pair in assigned_pairs:
            return
        assigned_pairs.add(pair)
        role_permission_rows.append({"role_id": pair[0], "permission_id": pair[1]})

    for role_code, prefixes in ROLE_PERMISSION_PREFIXES.items():
        for permission_code in permission_id_by_code:
            if permission_code.startswith(prefixes):
                grant(role_code, permission_code)
    for role_code, permission_codes in SUPPLEMENTAL_ROLE_PERMISSIONS.items():
        for permission_code in permission_codes:
            grant(role_code, permission_code)
    data["role_permissions"] = role_permission_rows

    # 初始超级管理员：强制首登改密；密码哈希由生成器随机口令计算。
    admin_rows = [{
        "id": 1,
        "platform_user_id": None,
        "resident_id": None,
        "source": "MANUAL",
        "username": admin_username,
        "password_hash": admin_password_hash,
        "real_name": "平台管理员",
        "phone_enc": "",
        "email": "",
        "avatar_text": "管",
        "status": "ACTIVE",
        "two_factor_enabled": False,
        "two_factor_secret_enc": "",
        "recovery_codes_hash": [],
        "is_super_admin": True,
        "last_login_at": None,
        "failed_attempts": 0,
        "locked_until": None,
        "version": 0,
        "must_change_password": True,
        "session_version": 0,
        "created_at": NOW,
        "updated_at": NOW,
    }]
    data["admin_users"] = admin_rows
    data["admin_user_roles"] = [{
        "admin_user_id": 1,
        "role_id": role_id_by_code["super_admin"],
    }]

    # 参数树：group.N → key → item。
    parameter_key_rows: list[dict] = []
    parameter_item_rows: list[dict] = []
    next_key_id = 1
    next_parameter_item_id = 1
    for group_sort, (group_label, items) in enumerate(PARAMETER_TREE.items()):
        group_id = next_key_id
        parameter_key_rows.append({
            "id": group_id,
            "parent_id": None,
            "label": group_label,
            "code": f"group.{group_sort}",
            "kind": "GROUP",
            "sort": group_sort,
            "status": "启用",
        })
        next_key_id += 1
        for item_sort, (code, value, description) in enumerate(items):
            key_id = next_key_id
            parameter_key_rows.append({
                "id": key_id,
                "parent_id": group_id,
                "label": description[:12],
                "code": code,
                "kind": "KEY",
                "sort": item_sort,
                "status": "启用",
            })
            parameter_item_rows.append({
                "id": next_parameter_item_id,
                "parameter_key_id": key_id,
                "name": code,
                "value": value,
                "description": description,
                "status": "启用",
                "updated_by": None,
                "created_at": NOW,
                "updated_at": NOW,
                "version": 0,
            })
            next_key_id += 1
            next_parameter_item_id += 1
    data["parameter_keys"] = parameter_key_rows
    data["parameter_items"] = parameter_item_rows

    # 搜索热词（与移动端 Mock 对齐）。
    data["hot_keywords"] = [
        {
            "id": position + 1,
            "keyword": keyword,
            "score": 100 - position,
            "sort": position,
            "status": "启用",
            "created_at": NOW,
        }
        for position, keyword in enumerate(HOT_KEYWORDS)
    ]

    return data


def validate_seed_data(seed_data: dict[str, list[dict]]) -> None:
    table_columns = {
        table.name: {column.name for column in table.columns}
        for table in Base.metadata.sorted_tables
    }
    for table_name, rows in seed_data.items():
        if not rows:
            continue
        unknown = set(rows[0]) - table_columns.get(table_name, set())
        if unknown:
            raise SystemExit(f"{table_name} 存在模型未定义的列：{sorted(unknown)}")

    pairs = [(row["role_id"], row["permission_id"]) for row in seed_data["role_permissions"]]
    if len(pairs) != len(set(pairs)):
        raise SystemExit("role_permissions 存在重复的角色-权限组合")

    region_ids = {row["id"] for row in seed_data["regions"]}
    for row in seed_data["regions"]:
        if row["parent_id"] is not None and row["parent_id"] not in region_ids:
            raise SystemExit(f"区划 {row['code']} 的 parent_id 无效")


# ---------------------------------------------------------------- 组装脚本


def build_sql(db_name: str, admin_username: str, admin_password: str) -> str:
    admin_password_hash = hash_password(admin_password)
    seed_data = build_seed_data(admin_username, admin_password_hash)
    validate_seed_data(seed_data)
    ddl = build_ddl()

    table_names = [table.name for table in Base.metadata.sorted_tables]
    data_order = [
        "regions",
        "communities",
        "item_categories",
        "dictionaries",
        "dictionary_items",
        "permissions",
        "roles",
        "role_permissions",
        "admin_users",
        "admin_user_roles",
        "parameter_keys",
        "parameter_items",
        "hot_keywords",
    ]
    missing_tables = [name for name in data_order if name not in table_names]
    if missing_tables:
        raise SystemExit(f"模型缺少基线数据表：{missing_tables}")

    lines: list[str] = []
    lines.append("-- ============================================================================")
    lines.append("-- 邻里小栈（NeighInn）生产库全量初始化脚本")
    lines.append("-- ============================================================================")
    lines.append(f"-- 目标数据库：{db_name}（PostgreSQL）")
    lines.append(f"-- Alembic 版本：{ALEMBIC_HEAD}（执行后后续升级仍用 alembic upgrade head）")
    lines.append(f"-- 初始管理员：{admin_username}（随机口令由生成脚本单独输出，首次登录强制改密）")
    lines.append("--")
    lines.append("-- 警告：本脚本会终止目标库现有连接并 DROP DATABASE，数据不可恢复，请先备份！")
    lines.append("--       执行前请停止后端容器/应用，执行完成后再启动，避免迁移与业务写入并发。")
    lines.append("-- 要求：执行账号需具备 CREATEDB 权限；若由 DBA 预建空库，可从「连接目标库」段开始执行。")
    lines.append("--       若账号无 CREATEDB 权限，可将第 0 段替换为（保留库、清空 schema）：")
    lines.append("--         \\connect :db_name")
    lines.append("--         DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
    lines.append("--       若集群没有 postgres 库，将 \\connect postgres 改为 \\connect template1。")
    lines.append("--")
    lines.append("-- 用法（psql）：")
    lines.append('--   psql "postgresql://postgres@127.0.0.1:5205/postgres" \\')
    lines.append("--        -v ON_ERROR_STOP=1 -f neighinn_prod_init.sql")
    lines.append("--   覆盖库名：追加 -v db_name=your_database")
    lines.append("--   注意：不要加 -1/--single-transaction（CREATE DATABASE 不能在事务块内执行）。")
    lines.append("-- ============================================================================")
    lines.append("")
    lines.append("\\set ON_ERROR_STOP on")
    lines.append("\\if :{?db_name}")
    lines.append("\\else")
    lines.append(f"\\set db_name {db_name}")
    lines.append("\\endif")
    lines.append("")
    lines.append("-- ---------------------------------------------------------------------------")
    lines.append("-- 0. 断开旧连接，删除并重建数据库")
    lines.append("-- ---------------------------------------------------------------------------")
    lines.append("\\connect postgres")
    lines.append("SELECT pg_terminate_backend(pid)")
    lines.append("FROM pg_stat_activity")
    lines.append("WHERE datname = :'db_name' AND pid <> pg_backend_pid();")
    lines.append('DROP DATABASE IF EXISTS :"db_name";')
    lines.append("CREATE DATABASE :\"db_name\" WITH ENCODING 'UTF8' TEMPLATE template0;")
    lines.append("\\connect :db_name")
    lines.append("")
    lines.append("SET client_encoding = 'UTF8';")
    lines.append("SET standard_conforming_strings = on;")
    lines.append("SET search_path = public;")
    lines.append("SET TIME ZONE 'UTC';")
    lines.append("-- 可选：统一数据库默认时区（应用连接串已通过 options=-c timezone=UTC 强制）：")
    lines.append("-- ALTER DATABASE :\"db_name\" SET timezone TO 'UTC';")
    lines.append("")
    lines.append("BEGIN;")
    lines.append("")
    lines.append("-- ---------------------------------------------------------------------------")
    lines.append(f"-- 1. 表结构（{len(table_names)} 张表 + Alembic 版本表）")
    lines.append("-- ---------------------------------------------------------------------------")
    lines.extend(ddl)
    lines.append("")
    lines.append("CREATE TABLE alembic_version (")
    lines.append("    version_num VARCHAR(32) NOT NULL,")
    lines.append("    CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)")
    lines.append(");")
    lines.append(f"INSERT INTO alembic_version (version_num) VALUES ('{ALEMBIC_HEAD}');")
    lines.append("")

    lines.append("-- ---------------------------------------------------------------------------")
    lines.append("-- 2. 基线数据")
    lines.append("-- ---------------------------------------------------------------------------")
    for table_name in data_order:
        rows = seed_data[table_name]
        lines.append(f"-- {table_name}: {len(rows)} 行")
        if table_name in {"communities", "hot_keywords"}:
            lines.append("-- 注：社区与搜索热词为初始夹具，可由后台按实际运营替换。")
        lines.extend(insert_block(table_name, rows))
        lines.append("")

    lines.append("-- ---------------------------------------------------------------------------")
    lines.append("-- 3. 重置自增序列（显式 ID 写入后必须推进序列，否则后续插入主键冲突）")
    lines.append("-- ---------------------------------------------------------------------------")
    serial_tables = [
        table.name for table in Base.metadata.sorted_tables
        if "id" in table.columns and table.columns["id"].autoincrement is not False
    ]
    for table_name in serial_tables:
        lines.append(
            f"SELECT setval(pg_get_serial_sequence('public.{table_name}', 'id'), "
            f"COALESCE((SELECT MAX(id) FROM public.{table_name}), 1), "
            f"(SELECT MAX(id) FROM public.{table_name}) IS NOT NULL);"
        )
    lines.append("")
    lines.append("COMMIT;")
    lines.append("")
    lines.append("ANALYZE;")
    lines.append("")
    lines.append("-- ============================================================================")
    lines.append("-- 完成。后续版本升级请执行：uv run alembic upgrade head")
    lines.append("-- 如使用独立应用账号（推荐），由 DBA 按实际账号补充授权：")
    lines.append(f"--   GRANT CONNECT ON DATABASE {db_name} TO neighinn_app;")
    lines.append("--   GRANT USAGE ON SCHEMA public TO neighinn_app;")
    lines.append("--   GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO neighinn_app;")
    lines.append("--   GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO neighinn_app;")
    lines.append("-- 如忘记初始管理员密码，可生成新哈希后执行：")
    lines.append("--   uv run python -c \"from src.core.security import hash_password; "
                 "print(hash_password('NewPassword#2026'))\"")
    lines.append("--   UPDATE admin_users SET password_hash = '<哈希>', "
                 "must_change_password = TRUE WHERE username = 'admin';")
    lines.append("-- ============================================================================")
    lines.append("")
    return "\n".join(lines)


def _generate_password(length: int = 20) -> str:
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*-_=+"
    while True:
        password = "".join(secrets.choice(alphabet) for _ in range(length))
        classes = sum((
            any(char.islower() for char in password),
            any(char.isupper() for char in password),
            any(char.isdigit() for char in password),
            any(char in "!@#$%^&*-_=+" for char in password),
        ))
        if classes == 4:
            return password


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-name", default="neighinn_prod", help="生产数据库名")
    parser.add_argument("--admin-username", default="admin", help="初始超级管理员账号")
    parser.add_argument(
        "--admin-password",
        default=None,
        help="初始超级管理员密码；缺省时随机生成并输出到终端",
    )
    parser.add_argument(
        "--out",
        default=str(BACKEND_ROOT / "deploy" / "neighinn_prod_init.sql"),
        help="输出 SQL 文件路径",
    )
    args = parser.parse_args()

    password = args.admin_password or _generate_password()
    sql = build_sql(args.db_name, args.admin_username, password)

    output = Path(args.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(sql, encoding="utf-8", newline="\n")

    table_count = len(Base.metadata.sorted_tables)
    try:
        display_path = output.relative_to(BACKEND_ROOT).as_posix()
    except ValueError:
        display_path = output.name
    print(f"已生成: {display_path}")
    print(f"表数量: {table_count} (+ alembic_version)")
    print(f"Alembic head: {ALEMBIC_HEAD}")
    print(f"初始管理员: {args.admin_username} / {password}")
    print("提示: 上述口令仅本次输出，不会写入 SQL；首次登录会强制修改密码。")


if __name__ == "__main__":
    main()
