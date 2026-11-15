from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import select

from src.core.deps import DbSession
from src.core.responses import ok
from src.db.models import ItemCategory
from src.services import param_service

router = APIRouter(tags=["c:catalog"])

AVATAR_PRESETS = [
    {"key": "person", "label": "邻里人物",
     "items": ["avatar-person-1", "avatar-person-2", "avatar-person-3"]},
    {"key": "animal", "label": "萌宠伙伴",
     "items": ["avatar-animal-1", "avatar-animal-2"]},
    {"key": "nature", "label": "自然风物",
     "items": ["avatar-nature-1", "avatar-nature-2"]},
]


@router.get("/config/app")
async def app_config(db: DbSession):
    """端侧只读配置子集：由后台参数配置下发（W04-05），发布即生效。"""
    return ok(await param_service.app_config_bundle(db))


@router.get("/categories")
async def categories(db: DbSession):
    """类目包（W04-03）：物品/生活/服务/成色四组。"""
    rows = list((await db.execute(
        select(ItemCategory).where(ItemCategory.status == "启用")
        .order_by(ItemCategory.sort, ItemCategory.id))).scalars().all())
    item_categories = [row.name for row in rows if row.parent_id is None]
    return ok({
        "itemCategories": item_categories,
        "conditions": ["全新", "九九新", "轻微使用痕迹", "明显使用痕迹", "有功能缺陷"],
        "lifeCategories": ["小区风景", "邻里日常", "个人风采", "萌宠生活"],
        "serviceCategories": ["邻里帮忙", "家政清洁", "维修安装", "代收代取", "技能服务"],
    })


@router.get("/avatars/presets")
async def avatar_presets():
    return ok(AVATAR_PRESETS)


@router.post("/track/batch")
async def track_batch():
    """埋点上报（W08 数据来源）。当前仅确认接收；分析管道 Phase 3。"""
    return ok({"accepted": 1})
