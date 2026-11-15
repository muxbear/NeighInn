"""AI 质检适配器（SRS 第 7 章 A-01~A-10）。

统一决策输出（与移动端 AuditReport / SRS 7 章 JSON 结构一致）：
    overall: PASS | FAIL | NEED_HUMAN_REVIEW
    confidence: 0.0 ~ 1.0
    dimensions: 图像质量 / 图文一致性 / 合规性 / 成色建议
    suggestions / risks / trace_id / model_version

生产接入真实多模态服务时实现 AuditProvider 协议即可，业务编排不变；
人工复核结论通过 ItemAudit 回流作为标注样本（A-10）。
"""

from __future__ import annotations

import uuid
from typing import Protocol

from src.core.config import settings
from src.db.models import Item, ItemMedia
from src.domain.enums import AiDecision

# 违禁品/敏感品关键词库（W03-02 二期做后台维护，当前静态基线 + 参数可覆盖）
BANNED_KEYWORDS = [
    "管制刀具", "枪支", "弹药", "处方药", "药品", "活体", "烟花爆竹",
    "易燃易爆", "高仿", "假货", "走私", "毒品", "迷奸", "窃听",
]

# 敏感内容（联系方式导流，命中转人工而非直接驳回，避免误杀，A-01 注）
SENSITIVE_PATTERNS = ["微信", "wechat", "vx:", "qq", "二维码", "手机号", "加我", "电话"]

BAD_CONDITIONS = ("明显使用痕迹", "有功能缺陷")


class AuditProvider(Protocol):
    name: str
    version: str

    async def audit(self, item: Item, media: list[ItemMedia]) -> dict: ...


def _base_confidence(media: list[ItemMedia]) -> float:
    photos = [m for m in media if m.media_type == "IMAGE"]
    videos = [m for m in media if m.media_type == "VIDEO"]
    invoices = [m for m in media if m.media_type == "INVOICE"]
    score = 0.62 + 0.04 * len(photos) + 0.05 * len(videos) + 0.03 * len(invoices)
    return min(0.99, round(score, 4))


class MockAuditProvider:
    """规则驱动的 Mock 质检：确定性输出，便于测试与联调。

    测试钩子（对象键/文本特征）：
    - 对象键含 blur → 该照片「模糊」；含 dark → 「过暗」；
    - 文本含违禁关键词 → 合规 FAIL；含联系方式 → 转人工；
    - 描述「全新」与成色「明显使用痕迹/有功能缺陷」冲突 → 图文不一致 FAIL。
    """

    name = "mock-multimodal"
    version = "mock-1.0.0"

    async def audit(self, item: Item, media: list[ItemMedia]) -> dict:
        images = [m for m in media if m.media_type == "IMAGE"]
        photos = len(images)
        issues_img: list[str] = []
        score_img = min(100, 55 + photos * 8)

        for index, m in enumerate(images, start=1):
            key = m.object_key.lower()
            if "blur" in key:
                issues_img.append(f"照片{index}模糊，请重新拍摄清晰照片")
                score_img -= 30
            if "dark" in key:
                issues_img.append(f"照片{index}过暗，请在自然光下重拍")
                score_img -= 25

        # A-01 结构要求：整体照 + 细节照（以照片数量近似）
        structure_ok = photos >= settings.min_item_images
        if not structure_ok:
            issues_img.append(f"照片数量不足（至少 {settings.min_item_images} 张，需含整体照与细节照）")
            score_img = min(score_img, 30)

        # A-02 图文一致性
        conflicts: list[str] = []
        text = f"{item.title}\n{item.description}\n{item.quality_desc}"
        if ("全新" in item.title or "全新" in item.quality_desc) and item.condition in BAD_CONDITIONS:
            conflicts.append(f"描述「全新」与所选成色「{item.condition}」不一致")
        if len(item.quality_desc or "") < 20:
            conflicts.append("质量说明不足 20 字，无法与照片比对")
        consistent = not conflicts

        # A-03 合规性
        labels = [kw for kw in BANNED_KEYWORDS if kw in text]
        sensitive = [p for p in SENSITIVE_PATTERNS if p in text]
        compliant = not labels

        # A-05 成色建议
        condition = item.condition or "轻微使用痕迹"

        risks: list[str] = []
        suggestions: list[str] = []
        if issues_img:
            suggestions.extend(issues_img)
        if conflicts:
            suggestions.append("请核对文字描述与照片、成色选择保持一致")
        if sensitive:
            risks.append("检测到疑似联系方式/导流信息，为保护交易安全需人工复核")
            suggestions.append("请移除图片或描述中的联系方式，交易沟通请在平台内进行")
        if labels:
            risks.append(f"命中禁售关键词：{'、'.join(labels)}")

        if not structure_ok or issues_img or not compliant or not consistent:
            overall = AiDecision.FAIL
        elif sensitive:
            overall = AiDecision.NEED_HUMAN_REVIEW
        else:
            overall = AiDecision.PASS

        return {
            "overall": overall,
            "confidence": _base_confidence(media),
            "dimensions": [
                {"name": "图像质量", "score": max(0, score_img), "issues": issues_img,
                 "photoCount": photos},
                {"name": "图文一致性", "pass": consistent, "conflicts": conflicts},
                {"name": "合规性", "pass": compliant, "labels": labels,
                 "sensitive": sensitive},
                {"name": "成色建议", "value": condition, "confidence": 0.8},
            ],
            "risks": risks,
            "suggestions": suggestions,
            "trace_id": uuid.uuid4().hex[:16],
            "model_version": f"{self.name}:{self.version}",
        }


_provider: AuditProvider = MockAuditProvider()


def get_provider() -> AuditProvider:
    return _provider


PIPELINE_STEPS = [
    {"key": "image", "title": "图像质量检测"},
    {"key": "consistency", "title": "图文一致性比对"},
    {"key": "compliance", "title": "合规与安全检测"},
    {"key": "summary", "title": "汇总评估报告"},
]


def build_progress(item: Item, report: dict | None) -> dict:
    """移动端 AuditProgress（mobile/models/audit.model.ts）。

    Mock 质检为同步执行：提交后立即可查最终结果；
    真实异步流水线接入后按 steps 逐步回填进度。
    """
    if report is None:
        return {
            "itemId": str(item.id), "status": "PROCESSING", "progress": 30,
            "currentText": "正在进行图像质量检测…",
            "steps": [
                {"key": "image", "title": "图像质量检测", "status": "PROCESSING"},
                {"key": "consistency", "title": "图文一致性比对", "status": "PENDING"},
                {"key": "compliance", "title": "合规与安全检测", "status": "PENDING"},
                {"key": "summary", "title": "汇总评估报告", "status": "PENDING"},
            ],
        }

    # 移动端进度只有 通过/驳回/超时 三态（详设 9.6）：
    # NEED_HUMAN_REVIEW 进入人工复核队列而非驳回，对用户展示为通过并附风险提示。
    passed = report["overall"] != AiDecision.FAIL
    steps = [
        {"key": "image", "title": "图像质量检测",
         "status": "DONE" if not report["dimensions"][0]["issues"] else "FAILED",
         "message": f"{report['dimensions'][0]['photoCount']} 张照片"},
        {"key": "consistency", "title": "图文一致性比对",
         "status": "DONE" if report["dimensions"][1]["pass"] else "FAILED",
         "message": "；".join(report["dimensions"][1]["conflicts"]) or "一致"},
        {"key": "compliance", "title": "合规与安全检测",
         "status": "DONE" if report["dimensions"][2]["pass"] else "FAILED",
         "message": "；".join(report["dimensions"][2]["labels"]) or "未发现违禁内容"},
        {"key": "summary", "title": "汇总评估报告", "status": "DONE",
         "message": "通过" if passed else "未通过"},
    ]
    reject_reasons = []
    if not passed:
        reject_reasons = [
            *report["dimensions"][0]["issues"],
            *report["dimensions"][1]["conflicts"],
            *[f"命中禁售关键词：{label}" for label in report["dimensions"][2]["labels"]],
        ]
    return {
        "itemId": str(item.id),
        "status": "PASSED" if passed else "REJECTED",
        "progress": 100,
        "currentText": "AI 质检完成" if passed else "AI 质检未通过",
        "steps": steps,
        "rejectReasons": reject_reasons or None,
        "report": {
            "passed": passed,
            "score": int(report["confidence"] * 100),
            "dimensions": [
                {"name": d["name"], "score": d.get("score", 100 if d.get("pass", True) else 0),
                 "desc": "；".join(d.get("issues") or d.get("conflicts") or d.get("labels") or [])
                          or (d.get("value") if isinstance(d.get("value"), str) else "正常")}
                for d in report["dimensions"]
            ],
            "risks": report["risks"],
            "suggestions": report["suggestions"],
            "traceId": report["trace_id"],
            "checkedAt": 0,  # 由调用方回填毫秒时间戳
        },
    }
