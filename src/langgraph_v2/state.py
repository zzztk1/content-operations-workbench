from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, TypedDict


ApprovalDecision = Literal["approve", "needs_edit", "reject"]
RunStatus = Literal[
    "pending",
    "running",
    "rewrite_pending",
    "ready_for_approval",
    "ready_for_export",
    "awaiting_topic_selection",
    "completed",
    "needs_manual_edit",
    "rejected",
    "failed",
]


class ResearchTopic(TypedDict, total=False):
    title: str
    reason: str
    heat_score: int
    target_audience: str
    content_angle: str


class ResearchPayload(TypedDict, total=False):
    topics: List[ResearchTopic]
    evidence: List[Dict[str, Any]]
    style_features: List[str]


class DraftPayload(TypedDict, total=False):
    title: str
    content: str
    tags: List[str]
    platform: str


class ImagePlan(TypedDict, total=False):
    prompt: str
    negative_prompt: str
    overlay_text: str
    visual_style: str
    aspect_ratio: str
    asset_type: str
    usage: str


class ImageAsset(TypedDict, total=False):
    status: str
    provider: str
    model: str
    asset_type: str
    usage: str
    requested_size: str
    prompt: str
    negative_prompt: str
    image_url: str
    local_path: str
    web_path: str
    mime_type: str
    retry_count: int
    latency_ms: float


class ReviewPayload(TypedDict, total=False):
    attraction_score: int
    accuracy_score: int
    platform_score: int
    total_score: int
    feedback: str
    passed: bool


class CoverVisualReview(TypedDict, total=False):
    theme_match_score: int
    readability_score: int
    composition_score: int
    overall_score: int
    passed: bool
    risk_flags: List[str]
    feedback: str
    review_mode: str
    vision_model: str


class ApprovalPayload(TypedDict, total=False):
    decision: ApprovalDecision
    note: str
    at: str


class ContentPackage(TypedDict, total=False):
    json_path: str
    markdown_path: str
    text_path: str
    html_path: str
    title: str
    image_url: str
    image_web_path: str
    cover_candidate_count: int
    cover_candidates_summary: List[Dict[str, Any]]
    text_image_consistency: Dict[str, Any]
    cover_visual_review: Dict[str, Any]
    image_assets_summary: List[Dict[str, Any]]
    publish_package: Dict[str, Any]


class EventPayload(TypedDict, total=False):
    node: str
    phase: str
    ts: str
    payload: Dict[str, Any]


class RuntimeFlags(TypedDict, total=False):
    llm_mock: bool
    image_mock: bool
    vision_review_mock: bool
    checkpointer_mock: bool
    enable_sse: bool
    enable_slowapi: bool
    enable_json_mode: bool


class MetricsPayload(TypedDict, total=False):
    totals: Dict[str, Any]
    node_metrics: List[Dict[str, Any]]


class MediaAgentState(TypedDict, total=False):
    run_id: str
    request_id: str
    thread_id: str
    graph_version: str
    status: RunStatus
    run_mode: Literal["auto", "guided"]
    guided_topic_locked: bool
    export_formats: List[str]
    brief: str
    platform: str
    style: str
    selected_topic: ResearchTopic
    research: ResearchPayload
    draft: DraftPayload
    adapted: DraftPayload
    image_plan: ImagePlan
    image_plans: List[ImagePlan]
    image_asset: ImageAsset
    image_assets: List[ImageAsset]
    cover_candidates: List[ImageAsset]
    cover_candidate_count: int
    cover_visual_review: CoverVisualReview
    review: ReviewPayload
    approval: ApprovalPayload
    approval_decision: ApprovalDecision
    approval_note: str
    reviewer_threshold: int
    max_revisions: int
    revision_count: int
    review_feedback: str
    trace: List[str]
    events: List[EventPayload]
    metrics: MetricsPayload
    errors: List[Dict[str, Any]]
    content_package: ContentPackage
    platform_rule: Dict[str, Any]
    publish_package: Dict[str, Any]
    text_image_consistency: Dict[str, Any]
    runtime_flags: RuntimeFlags
