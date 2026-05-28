from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, List


PLATFORM_RULES: Dict[str, Dict[str, Any]] = {
    "公众号": {
        "label": "微信公众号",
        "content_shape": "长文观点/趋势观察",
        "length_hint": "900到1400字",
        "paragraph_hint": "6到9段自然段，适合深度阅读",
        "tone_hint": "稳重、清晰、有观点，允许案例和趋势判断",
        "tag_count": "2到3个",
        "image_targets": {
            "cover": 1,
            "body": 3,
            "card": 0,
            "summary": 1,
        },
        "image_types": ["cover", "body", "summary"],
        "publish_checks": [
            "标题避免夸张承诺，适合公众号信息流",
            "正文段落完整，有开头观点、展开论证和收束",
            "至少准备1张封面和3张正文配图",
            "图片无水印、无侵权暗示、无低清晰度问题",
        ],
        "publish_steps": [
            "复制标题",
            "粘贴正文并按自然段排版",
            "上传封面图",
            "按段落插入正文配图",
            "预览后手动发布",
        ],
    },
    "小红书": {
        "label": "小红书",
        "content_shape": "短笔记/种草/经验帖",
        "length_hint": "180到320字",
        "paragraph_hint": "2到4段短段落，节奏快",
        "tone_hint": "口语化、强钩子、可收藏，标签更丰富",
        "tag_count": "6到10个",
        "image_targets": {
            "cover": 1,
            "body": 0,
            "card": 6,
            "summary": 1,
        },
        "image_types": ["cover", "card", "summary"],
        "publish_checks": [
            "标题和首句有明确钩子，但避免夸大疗效/收益",
            "标签数量充足，包含场景、痛点和人群关键词",
            "准备6到9张卡片图，首图承担封面职责",
            "图片比例适合移动端浏览，文字不过密",
        ],
        "publish_steps": [
            "复制标题和笔记正文",
            "上传封面和卡片图",
            "粘贴标签",
            "检查敏感词和商业化表述",
            "手动发布或存草稿",
        ],
    },
    "知乎": {
        "label": "知乎",
        "content_shape": "问答/分析文",
        "length_hint": "500到900字",
        "paragraph_hint": "4到7段，先回答再论证",
        "tone_hint": "理性、解释型、逻辑清楚，有观点和依据",
        "tag_count": "2到4个",
        "image_targets": {
            "cover": 1,
            "body": 1,
            "card": 0,
            "summary": 1,
        },
        "image_types": ["cover", "body", "summary"],
        "publish_checks": [
            "开头直接回答问题，后文分层论证",
            "避免空泛鸡汤，保留解释和反例",
            "至少准备1张封面和1张解释型配图",
            "标签与问题领域一致",
        ],
        "publish_steps": [
            "复制标题作为问题或回答标题",
            "粘贴正文并检查逻辑层次",
            "插入解释型配图",
            "补充标签",
            "预览后手动发布",
        ],
    },
}


DEFAULT_PLATFORM_RULE = PLATFORM_RULES["小红书"]


def get_platform_rule(platform: str) -> Dict[str, Any]:
    return deepcopy(PLATFORM_RULES.get(platform, DEFAULT_PLATFORM_RULE))


def list_platform_rules() -> List[Dict[str, Any]]:
    return [
        {"platform": name, **deepcopy(rule)}
        for name, rule in PLATFORM_RULES.items()
    ]

