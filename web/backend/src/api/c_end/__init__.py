from __future__ import annotations

from fastapi import APIRouter

from src.api.c_end import (
    auth,
    broadcasts,
    catalog,
    communities,
    engage,
    home,
    items,
    life,
    notifications,
    orders,
    payments,
    reports,
    services,
    social,
    uploads,
    users,
    wallet,
    ws,
)

c_router = APIRouter()

for module in (
    auth,
    catalog,
    home,
    items,
    engage,
    life,
    services,
    broadcasts,
    orders,
    payments,
    wallet,
    notifications,
    social,
    communities,
    users,
    uploads,
    reports,
    ws,
):
    c_router.include_router(module.router)
