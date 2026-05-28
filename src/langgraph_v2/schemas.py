from __future__ import annotations

from typing import Any, Dict, List, Literal

from pydantic import BaseModel, Field, model_validator


ApprovalDecision = Literal["approve", "needs_edit", "reject"]


class ResearchTopicModel(BaseModel):
    title: str
    reason: str = ""
    heat_score: int = 5
    target_audience: str = ""
    content_angle: str = ""

    @model_validator(mode="after")
    def normalize(self) -> "ResearchTopicModel":
        self.title = self.title.strip()[:32]
        self.reason = self.reason.strip()[:80]
        self.target_audience = self.target_audience.strip()[:24]
        self.content_angle = self.content_angle.strip()[:24]
        if self.heat_score > 10:
            self.heat_score = max(1, min(10, round(self.heat_score / 10)))
        else:
            self.heat_score = max(1, min(10, self.heat_score))
        return self


class ResearchPayloadModel(BaseModel):
    topics: List[ResearchTopicModel] = Field(default_factory=list)
    evidence: List[Dict[str, Any]] = Field(default_factory=list)

    @model_validator(mode="after")
    def normalize(self) -> "ResearchPayloadModel":
        self.topics = self.topics[:3]
        return self


class DraftPayloadModel(BaseModel):
    title: str
    content: str
    tags: List[str] = Field(default_factory=list)
    platform: str = ""

    @model_validator(mode="before")
    @classmethod
    def coerce_common_shapes(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value

        payload = dict(value)
        for wrapper_key in ("draft", "data", "result", "output"):
            wrapped = payload.get(wrapper_key)
            if isinstance(wrapped, dict):
                payload = dict(wrapped)
                break

        aliases = {
            "title": ("headline", "post_title", "subject"),
            "content": ("body", "copy", "draft_text", "post_content"),
            "platform": ("channel", "target_platform"),
        }
        for target_key, candidates in aliases.items():
            if payload.get(target_key):
                continue
            for candidate in candidates:
                if payload.get(candidate):
                    payload[target_key] = payload[candidate]
                    break

        tags_value = payload.get("tags")
        if isinstance(tags_value, str):
            normalized_tags = tags_value.replace("，", ",").replace(" ", ",")
            payload["tags"] = [item.strip() for item in normalized_tags.split(",") if item.strip()]
        elif tags_value is None:
            payload["tags"] = []

        return payload

    @model_validator(mode="after")
    def normalize(self) -> "DraftPayloadModel":
        self.title = self.title.strip()[:48]
        self.content = self.content.strip()
        cleaned_tags: List[str] = []
        for tag in self.tags:
            value = tag.strip()
            if not value:
                continue
            if not value.startswith("#"):
                value = f"#{value}"
            if value not in cleaned_tags:
                cleaned_tags.append(value)
        self.tags = cleaned_tags[:5]
        self.platform = self.platform.strip()
        return self


class ImagePlanModel(BaseModel):
    prompt: str
    negative_prompt: str = ""
    overlay_text: str = ""
    visual_style: str = ""
    aspect_ratio: str = "4:3"
    asset_type: str = "cover"
    usage: str = "封面"

    @model_validator(mode="after")
    def normalize(self) -> "ImagePlanModel":
        self.prompt = self.prompt.strip()[:1000]
        self.negative_prompt = self.negative_prompt.strip()[:240]
        self.overlay_text = self.overlay_text.strip()[:48]
        self.visual_style = self.visual_style.strip()[:80]
        self.aspect_ratio = self.aspect_ratio.strip() or "4:3"
        self.asset_type = self.asset_type.strip()[:24] or "cover"
        self.usage = self.usage.strip()[:40] or "封面"
        return self


class ImageAssetModel(BaseModel):
    status: str
    provider: str = ""
    model: str = ""
    asset_type: str = "cover"
    usage: str = "封面"
    requested_size: str = ""
    prompt: str = ""
    negative_prompt: str = ""
    image_url: str = ""
    local_path: str = ""
    web_path: str = ""
    mime_type: str = ""
    retry_count: int = 0
    latency_ms: float = 0.0


class ReviewPayloadModel(BaseModel):
    attraction_score: int = 7
    accuracy_score: int = 7
    platform_score: int = 7
    total_score: int = 21
    feedback: str = "Please improve clarity and hooks."
    passed: bool = False

    @model_validator(mode="after")
    def normalize(self) -> "ReviewPayloadModel":
        total = self.attraction_score + self.accuracy_score + self.platform_score
        self.total_score = total
        self.passed = self.total_score >= 21
        return self


class CoverVisualReviewPayloadModel(BaseModel):
    theme_match_score: int = 0
    readability_score: int = 0
    composition_score: int = 0
    overall_score: int = 0
    passed: bool = False
    risk_flags: List[str] = Field(default_factory=list)
    feedback: str = ""
    review_mode: str = ""
    vision_model: str = ""

    @model_validator(mode="after")
    def normalize(self) -> "CoverVisualReviewPayloadModel":
        self.theme_match_score = max(0, min(100, int(self.theme_match_score)))
        self.readability_score = max(0, min(100, int(self.readability_score)))
        self.composition_score = max(0, min(100, int(self.composition_score)))
        self.overall_score = max(0, min(100, int(self.overall_score)))
        if not self.risk_flags:
            self.risk_flags = []
        blocked = any("block" in str(f).lower() for f in self.risk_flags)
        self.passed = bool(self.overall_score >= 65 and not blocked)
        return self


class ApprovalPayloadModel(BaseModel):
    decision: ApprovalDecision
    note: str = ""
    at: str


class ExportPackageModel(BaseModel):
    run_id: str
    request_id: str = ""
    brief: str
    platform: str
    style: str
    export_formats: List[str] = Field(default_factory=list)
    title: str
    content: str
    tags: List[str] = Field(default_factory=list)
    image_plan: Dict[str, Any] = Field(default_factory=dict)
    image_plans: List[Dict[str, Any]] = Field(default_factory=list)
    image_asset: Dict[str, Any] = Field(default_factory=dict)
    image_assets: List[Dict[str, Any]] = Field(default_factory=list)
    cover_candidates: List[Dict[str, Any]] = Field(default_factory=list)
    platform_rule: Dict[str, Any] = Field(default_factory=dict)
    publish_package: Dict[str, Any] = Field(default_factory=dict)
    cover_visual_review: Dict[str, Any] = Field(default_factory=dict)
    review: Dict[str, Any] = Field(default_factory=dict)
    approval: Dict[str, Any] = Field(default_factory=dict)
    trace: List[str] = Field(default_factory=list)
    revision_count: int = 0
    graph_version: str = ""
    metrics_summary: Dict[str, Any] = Field(default_factory=dict)
    text_image_consistency: Dict[str, Any] = Field(default_factory=dict)
    created_at: str
