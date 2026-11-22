from __future__ import annotations

from fastapi import APIRouter

from src.api.admin import (
    accounts,
    auth,
    communication,
    communities,
    community_admins,
    content_ops,
    dashboard,
    exports,
    files,
    finance,
    governance,
    governance_extra,
    operations,
    residents,
    resources,
    system,
    users,
)

admin_router = APIRouter()

for module in (
    auth,
    accounts,
    community_admins,
    dashboard,
    communities,
    residents,
    operations,
    content_ops,
    communication,
    governance,
    governance_extra,
    finance,
    resources,
    system,
    users,
    files,
    exports,
):
    admin_router.include_router(module.router)
