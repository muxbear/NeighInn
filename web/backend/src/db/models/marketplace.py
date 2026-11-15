from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.db.base import Base
from src.db.models.common import BigIntPk, Entity, JsonDict, utcnow


class ItemCategory(Base):
    """两级物品类目（W04-03）：增删改、排序、图标。"""

    __tablename__ = "item_categories"

    id: Mapped[int] = mapped_column(BigIntPk, primary_key=True, autoincrement=True)
    parent_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("item_categories.id"), index=True)
    name: Mapped[str] = mapped_column(String(64))
    icon: Mapped[str] = mapped_column(String(64), default="")
    sort: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="启用")


class Item(Entity):
    """社区物品（SRS 9.1 Item）。与小区强绑定（BR-02）；三种交易方式必选其一（BR-06）；
    AI 质检通过 + 人工复核后才可上架（BR-04）；30 天有效期（BR-07，可配置）。

    状态机见 domain/enums.py ItemStatus / state.py。"""

    __tablename__ = "items"

    id: Mapped[int] = mapped_column(BigIntPk, primary_key=True, autoincrement=True)
    community_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("communities.id"), index=True)
    seller_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), index=True)
    category_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("item_categories.id"), index=True)
    title: Mapped[str] = mapped_column(String(120), index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    quality_desc: Mapped[str] = mapped_column(Text, default="")
    # MONETARY / FREE_GIFT / BARTER
    trade_type: Mapped[str] = mapped_column(String(16), index=True)
    price_cents: Mapped[int] = mapped_column(BigInteger, default=0)
    # 全新 / 九九新 / 轻微使用痕迹 / 明显使用痕迹 / 有功能缺陷（M03-01 五档）
    condition: Mapped[str] = mapped_column(String(32), default="")
    # 互换专用：期望交换的物品描述（结构化标签 + 自由文本，BR-13）
    barter_expect: Mapped[str] = mapped_column(Text, default="")
    expect_time: Mapped[str] = mapped_column(String(64), default="")
    status: Mapped[str] = mapped_column(String(20), default="DRAFT", index=True)
    recommended: Mapped[bool] = mapped_column(Boolean, default=False)
    reject_reason: Mapped[str] = mapped_column(String(500), default="")
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    # {"views": 0, "favorites": 0, "comments": 0}
    stats: Mapped[dict] = mapped_column(JsonDict, default=dict)


class ItemMedia(Base):
    """物品媒体（BR-05：3–12 张多角度照片；可选视频 ≤60s/100MB 与发票凭证，M03-03）。
    存对象键，私有桶签名 URL 访问。"""

    __tablename__ = "item_media"

    id: Mapped[int] = mapped_column(BigIntPk, primary_key=True, autoincrement=True)
    item_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("items.id"), index=True)
    object_key: Mapped[str] = mapped_column(String(255))
    # IMAGE / VIDEO / INVOICE
    media_type: Mapped[str] = mapped_column(String(16), default="IMAGE", index=True)
    sort: Mapped[int] = mapped_column(Integer, default=0)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    duration_ms: Mapped[int | None] = mapped_column(Integer)


class ItemAudit(Base):
    """AI 质检 + 人工复核记录（SRS 7 章、W03-01、A-01~A-10）。
    统一决策输出：overall(PASS/FAIL/NEED_HUMAN_REVIEW)、confidence、dimensions、suggestions、trace_id。
    人工复核结论回传作为标注样本（A-10）；AI 质检是上架必要非充分条件（11.1）。"""

    __tablename__ = "item_audits"

    id: Mapped[int] = mapped_column(BigIntPk, primary_key=True, autoincrement=True)
    item_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("items.id"), index=True)
    overall: Mapped[str] = mapped_column(String(24), index=True)
    confidence: Mapped[float | None] = mapped_column(Numeric(5, 4))
    # [{"name": "图像质量", "score": 0-100, "issues": [...]}, {"name": "图文一致性", ...},
    #  {"name": "合规性", ...}, {"name": "成色建议", "value": "九九新"}]
    dimensions: Mapped[dict] = mapped_column(JsonDict, default=list)
    risks: Mapped[dict] = mapped_column(JsonDict, default=list)
    suggestions: Mapped[dict] = mapped_column(JsonDict, default=list)
    # 人工复核决策：APPROVE / REJECT / DOWNGRADE（W03-01）
    decision: Mapped[str] = mapped_column(String(16), default="", index=True)
    reviewer_id: Mapped[int | None] = mapped_column(BigInteger)
    review_note: Mapped[str] = mapped_column(String(500), default="")
    trace_id: Mapped[str] = mapped_column(String(32), default="", index=True)
    model_version: Mapped[str] = mapped_column(String(32), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
