from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple


def _strip_tag(t: str) -> str:
    s = (t or "").strip()
    if s.startswith("#"):
        s = s[1:].strip()
    return s


def _ascii_words(text: str, limit: int) -> List[str]:
    seen: set = set()
    out: List[str] = []
    for m in re.finditer(r"\b[a-zA-Z][a-zA-Z0-9]{3,}\b", text):
        w = m.group(0).lower()
        if w in seen:
            continue
        seen.add(w)
        out.append(w)
        if len(out) >= limit:
            break
    return out


def _cjk_bigrams(title: str, limit: int) -> List[str]:
    t = re.sub(r"[^\u4e00-\u9fff]", "", title or "")
    seen: set = set()
    out: List[str] = []
    for i in range(len(t) - 1):
        bg = t[i : i + 2]
        if bg not in seen:
            seen.add(bg)
            out.append(bg)
        if len(out) >= limit:
            break
    return out


def _reference_keywords(
    brief: str,
    title: str,
    content: str,
    tags: List[str],
    max_keywords: int = 20,
) -> List[str]:
    """Cheap keyword list from article-side text (no ML)."""
    seen: set = set()
    out: List[str] = []

    for raw in tags or []:
        s = _strip_tag(raw)
        if len(s) >= 2 and s not in seen:
            seen.add(s)
            out.append(s)
        if len(out) >= max_keywords:
            return out

    for bg in _cjk_bigrams(title, 14):
        if bg not in seen:
            seen.add(bg)
            out.append(bg)
        if len(out) >= max_keywords:
            return out

    head = f"{brief or ''}\n{(content or '')[:900]}"
    for bg in _cjk_bigrams(head, 10):
        if bg not in seen:
            seen.add(bg)
            out.append(bg)
        if len(out) >= max_keywords:
            return out

    for w in _ascii_words(f"{title}\n{brief}\n{content[:600]}", 10):
        if w not in seen:
            seen.add(w)
            out.append(w)
        if len(out) >= max_keywords:
            break

    return out[:max_keywords]


def _image_side_text(image_plan: Dict[str, Any], image_asset: Dict[str, Any]) -> str:
    parts: List[str] = []
    for key in ("prompt", "negative_prompt", "overlay_text", "visual_style"):
        v = (image_plan or {}).get(key) or ""
        if isinstance(v, str) and v.strip():
            parts.append(v.strip())
    for key in ("prompt", "negative_prompt"):
        v = (image_asset or {}).get(key) or ""
        if isinstance(v, str) and v.strip():
            parts.append(v.strip())
    return "\n".join(parts)


def _keyword_in_haystack(haystack: str, kw: str) -> bool:
    if re.search(r"[\u4e00-\u9fff]", kw):
        return kw in haystack
    return kw.lower() in haystack.lower()


def compute_text_image_consistency(
    *,
    brief: str,
    title: str,
    content: str,
    tags: List[str],
    image_plan: Dict[str, Any],
    image_asset: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Heuristic overlap between article text/tags and image plan/prompt text.
    No vision models — string overlap only.
    """
    haystack = _image_side_text(image_plan, image_asset)
    keywords = _reference_keywords(brief, title, content, tags)

    if not haystack.strip():
        return {
            "status": "poor",
            "score": 0.0,
            "matched_keywords": [],
            "missing_keywords": keywords,
            "note": "缺少可用于比对的封面文案（image_plan / image_asset 中无有效文本）。",
        }

    if not keywords:
        return {
            "status": "unknown",
            "score": 0.0,
            "matched_keywords": [],
            "missing_keywords": [],
            "note": "未能从标题/正文/标签中提取关键词，跳过一致性比对。",
        }

    matched: List[str] = []
    missing: List[str] = []
    for kw in keywords:
        if _keyword_in_haystack(haystack, kw):
            matched.append(kw)
        else:
            missing.append(kw)

    ratio = len(matched) / max(1, len(keywords))
    score = round(min(1.0, max(0.0, ratio)), 3)

    if score >= 0.45:
        status = "ok"
    elif score >= 0.2:
        status = "weak"
    else:
        status = "poor"

    note = (
        f"基于标题/正文/标签与封面 prompt 等文本的轻量关键词重合（{len(matched)}/{len(keywords)}），"
        "非图像语义理解。"
    )
    return {
        "status": status,
        "score": score,
        "matched_keywords": matched[:24],
        "missing_keywords": missing[:24],
        "note": note,
    }


def validate_consistency_shape(payload: Any) -> Tuple[bool, str]:
    """Offline validator for benchmark scripts."""
    if not isinstance(payload, dict):
        return False, "not_an_object"
    for key in ("status", "score", "matched_keywords", "missing_keywords", "note"):
        if key not in payload:
            return False, f"missing_{key}"
    if payload["status"] not in {"ok", "weak", "poor", "unknown"}:
        return False, "bad_status"
    sc = payload["score"]
    if not isinstance(sc, (int, float)) or sc < 0 or sc > 1:
        return False, "bad_score"
    if not isinstance(payload["matched_keywords"], list) or not isinstance(
        payload["missing_keywords"], list
    ):
        return False, "bad_keyword_lists"
    if not isinstance(payload["note"], str):
        return False, "bad_note"
    for lst in (payload["matched_keywords"], payload["missing_keywords"]):
        for item in lst:
            if not isinstance(item, str):
                return False, "keyword_not_str"
    return True, "ok"
