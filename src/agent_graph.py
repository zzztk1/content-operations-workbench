import json
import os
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_json_loads(raw: str, fallback: Any) -> Any:
    try:
        return json.loads(raw)
    except Exception:
        return fallback


@dataclass
class MetricsContext:
    node_metrics: List[Dict[str, Any]] = field(default_factory=list)
    totals: Dict[str, Any] = field(
        default_factory=lambda: {
            "latency_ms": 0.0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "estimated_cost_usd": 0.0,
            "error_count": 0,
        }
    )

    def begin(self, node_name: str) -> float:
        return time.perf_counter()

    def end(
        self,
        node_name: str,
        start_time: float,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        total_tokens: int = 0,
        estimated_cost_usd: float = 0.0,
        error: Optional[str] = None,
    ) -> None:
        latency_ms = (time.perf_counter() - start_time) * 1000
        self.node_metrics.append(
            {
                "node": node_name,
                "latency_ms": round(latency_ms, 2),
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total_tokens,
                "estimated_cost_usd": round(estimated_cost_usd, 6),
                "error": error,
                "ts": _utc_now(),
            }
        )
        self.totals["latency_ms"] += latency_ms
        self.totals["prompt_tokens"] += prompt_tokens
        self.totals["completion_tokens"] += completion_tokens
        self.totals["total_tokens"] += total_tokens
        self.totals["estimated_cost_usd"] += estimated_cost_usd
        if error:
            self.totals["error_count"] += 1

    def as_dict(self) -> Dict[str, Any]:
        return {
            "node_metrics": self.node_metrics,
            "totals": {
                "latency_ms": round(self.totals["latency_ms"], 2),
                "prompt_tokens": self.totals["prompt_tokens"],
                "completion_tokens": self.totals["completion_tokens"],
                "total_tokens": self.totals["total_tokens"],
                "estimated_cost_usd": round(self.totals["estimated_cost_usd"], 6),
                "error_count": self.totals["error_count"],
            },
        }


class SQLiteCheckpointStore:
    def __init__(self, db_path: str) -> None:
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.db_path = db_path
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS workflow_runs (
                    run_id TEXT PRIMARY KEY,
                    state_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.commit()

    def save(self, run_id: str, state: Dict[str, Any], status: str) -> None:
        payload = json.dumps(state, ensure_ascii=False)
        ts = _utc_now()
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO workflow_runs(run_id, state_json, status, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    state_json=excluded.state_json,
                    status=excluded.status,
                    updated_at=excluded.updated_at
                """,
                (run_id, payload, status, ts),
            )
            conn.commit()

    def load(self, run_id: str) -> Optional[Dict[str, Any]]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT run_id, state_json, status, updated_at FROM workflow_runs WHERE run_id=?",
                (run_id,),
            ).fetchone()
        if not row:
            return None
        return {
            "run_id": row[0],
            "state": _safe_json_loads(row[1], {}),
            "status": row[2],
            "updated_at": row[3],
        }

    def list_recent(self, limit: int = 20) -> List[Dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT run_id, status, updated_at
                FROM workflow_runs
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [{"run_id": r[0], "status": r[1], "updated_at": r[2]} for r in rows]


class KnowledgeBase:
    """Minimal local file-based knowledge retriever."""

    def __init__(self) -> None:
        self.sample_dir = os.path.join(os.path.dirname(__file__), "..", "sample_posts")

    def search(self, query: str, top_k: int = 3) -> List[str]:
        if not os.path.isdir(self.sample_dir):
            return []
        hits: List[Dict[str, Any]] = []
        query_terms = {t.strip().lower() for t in query.split() if t.strip()}
        for filename in os.listdir(self.sample_dir):
            if not filename.lower().endswith(".txt"):
                continue
            path = os.path.join(self.sample_dir, filename)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read()
            except Exception:
                continue
            text = content.lower()
            lexical_score = sum(1 for t in query_terms if t in text)
            hits.append(
                {"filename": filename, "content": content, "score": lexical_score}
            )
        hits.sort(key=lambda x: x["score"], reverse=True)
        if any(term in {"公众号", "知乎"} for term in query_terms) and not any(
            h["score"] > 0 for h in hits
        ):
            return []
        return [h["content"] for h in hits[:top_k] if h["score"] > 0] or [
            h["content"] for h in hits[:top_k]
        ]


class MediaAgentGraph:
    """
    Fast-track workflow engine for project2:
    brief -> research -> draft -> review -> approval -> export
    with retry loop, checkpoint persistence, and metrics.
    """

    MODEL_PRICE_PER_1K = {
        "deepseek-chat": 0.001,
        "gpt-4o-mini": 0.0006,
        "gpt-4.1-mini": 0.0008,
    }

    def __init__(self) -> None:
        self.api_key = os.getenv("DEEPSEEK_API_KEY", "")
        self.api_base = os.getenv("DEEPSEEK_API_BASE", "https://api.deepseek.com")
        self.model = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
        self.llm_mock = os.getenv("LLM_MOCK", "false").lower() == "true"
        self.client = (
            OpenAI(api_key=self.api_key, base_url=self.api_base)
            if self.api_key and not self.llm_mock
            else None
        )
        self.kb = KnowledgeBase()
        self.checkpoint = SQLiteCheckpointStore(
            db_path=os.path.join(os.path.dirname(__file__), "..", "data", "workflow.db")
        )

    def _estimate_cost(self, total_tokens: int) -> float:
        unit = self.MODEL_PRICE_PER_1K.get(self.model, 0.001)
        return (total_tokens / 1000.0) * unit

    def _call_llm(
        self, system_prompt: str, user_prompt: str, temperature: float = 0.7
    ) -> Dict[str, Any]:
        if self.llm_mock or not self.client:
            mocked = {
                "text": json.dumps(
                    {
                        "mock": True,
                        "summary": "mock response generated in LLM_MOCK mode",
                    },
                    ensure_ascii=False,
                ),
                "usage": {"prompt_tokens": 80, "completion_tokens": 120, "total_tokens": 200},
            }
            return mocked
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=temperature,
            max_tokens=1800,
        )
        usage = response.usage
        return {
            "text": response.choices[0].message.content or "",
            "usage": {
                "prompt_tokens": int(getattr(usage, "prompt_tokens", 0)),
                "completion_tokens": int(getattr(usage, "completion_tokens", 0)),
                "total_tokens": int(getattr(usage, "total_tokens", 0)),
            },
        }

    def _extract_json(self, raw: str, fallback: Any) -> Any:
        try:
            return json.loads(raw)
        except Exception:
            pass
        start = raw.find("{")
        end = raw.rfind("}")
        if start != -1 and end != -1 and start < end:
            try:
                return json.loads(raw[start : end + 1])
            except Exception:
                pass
        start = raw.find("[")
        end = raw.rfind("]")
        if start != -1 and end != -1 and start < end:
            try:
                return json.loads(raw[start : end + 1])
            except Exception:
                pass
        return fallback

    def node_research(self, state: Dict[str, Any], metrics: MetricsContext) -> Dict[str, Any]:
        started = metrics.begin("research")
        system_prompt = (
            "You are a content research strategist. Return strict JSON with a `topics` array."
        )
        user_prompt = (
            f"brief={state['brief']}\n"
            f"platform={state['platform']}\n"
            "Return 5 candidate topics with fields: title, reason, heat_score, target_audience, content_angle."
        )
        error = None
        payload: Dict[str, Any]
        usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        try:
            llm = self._call_llm(system_prompt, user_prompt, temperature=0.5)
            usage = llm["usage"]
            parsed = self._extract_json(llm["text"], fallback={"topics": []})
            topics = parsed.get("topics", []) if isinstance(parsed, dict) else []
            if not topics:
                topics = [
                    {
                        "title": state["brief"],
                        "reason": "fallback topic generated due empty parse",
                        "heat_score": 6,
                        "target_audience": "general audience",
                        "content_angle": "problem-solution",
                    }
                ]
            payload = {"topics": topics}
        except Exception as exc:
            error = str(exc)
            payload = {
                "topics": [
                    {
                        "title": state["brief"],
                        "reason": "research fallback due exception",
                        "heat_score": 5,
                        "target_audience": "general audience",
                        "content_angle": "practical guide",
                    }
                ]
            }
        cost = self._estimate_cost(usage["total_tokens"])
        metrics.end(
            "research",
            started,
            usage["prompt_tokens"],
            usage["completion_tokens"],
            usage["total_tokens"],
            cost,
            error,
        )
        state["research"] = payload
        state["trace"].append("research")
        return state

    def node_writer(self, state: Dict[str, Any], metrics: MetricsContext) -> Dict[str, Any]:
        started = metrics.begin("writer")
        topic = state["selected_topic"]["title"]
        refs = self.kb.search(topic, top_k=3)
        refs_text = "\n---\n".join(refs[:3]) if refs else "no reference posts found"
        system_prompt = (
            "You are a senior content writer. Return strict JSON with title, content, tags."
        )
        user_prompt = (
            f"platform={state['platform']}\nstyle={state['style']}\n"
            f"topic={topic}\n"
            f"feedback={state.get('review_feedback', '')}\n"
            f"references={refs_text[:2000]}"
        )
        usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        error = None
        try:
            llm = self._call_llm(system_prompt, user_prompt, temperature=0.8)
            usage = llm["usage"]
            parsed = self._extract_json(llm["text"], fallback={})
            result = {
                "title": parsed.get("title", f"{topic} | {state['platform']}"),
                "content": parsed.get("content", llm["text"]),
                "tags": parsed.get("tags", ["#AI", "#内容运营"]),
            }
        except Exception as exc:
            error = str(exc)
            result = {
                "title": f"{topic} | fallback",
                "content": f"自动降级写作结果。原因为：{exc}",
                "tags": ["#fallback"],
            }
        cost = self._estimate_cost(usage["total_tokens"])
        metrics.end(
            "writer",
            started,
            usage["prompt_tokens"],
            usage["completion_tokens"],
            usage["total_tokens"],
            cost,
            error,
        )
        state["draft"] = result
        state["trace"].append("writer")
        return state

    def node_reviewer(self, state: Dict[str, Any], metrics: MetricsContext) -> Dict[str, Any]:
        started = metrics.begin("reviewer")
        draft = state["draft"]["content"]
        system_prompt = (
            "You are a strict reviewer. Return strict JSON with attraction_score, accuracy_score, "
            "platform_score, total_score, feedback."
        )
        user_prompt = (
            f"platform={state['platform']}\n"
            f"content={draft[:2500]}\n"
            "score each item in [1,10]. total_score must be sum of 3 scores."
        )
        usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        error = None
        try:
            llm = self._call_llm(system_prompt, user_prompt, temperature=0.2)
            usage = llm["usage"]
            parsed = self._extract_json(llm["text"], fallback={})
            a = int(parsed.get("attraction_score", 7))
            b = int(parsed.get("accuracy_score", 7))
            c = int(parsed.get("platform_score", 7))
            total = int(parsed.get("total_score", a + b + c))
            review = {
                "attraction_score": a,
                "accuracy_score": b,
                "platform_score": c,
                "total_score": total,
                "feedback": parsed.get("feedback", "Please improve clarity and hooks."),
            }
        except Exception as exc:
            error = str(exc)
            review = {
                "attraction_score": 6,
                "accuracy_score": 6,
                "platform_score": 6,
                "total_score": 18,
                "feedback": f"reviewer fallback due error: {exc}",
            }
        cost = self._estimate_cost(usage["total_tokens"])
        metrics.end(
            "reviewer",
            started,
            usage["prompt_tokens"],
            usage["completion_tokens"],
            usage["total_tokens"],
            cost,
            error,
        )
        state["review"] = review
        state["review_feedback"] = review["feedback"]
        state["trace"].append("reviewer")
        return state

    def node_adapter(self, state: Dict[str, Any], metrics: MetricsContext) -> Dict[str, Any]:
        started = metrics.begin("adapter")
        usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        error = None
        if state["platform"] == "小红书":
            state["adapted"] = {
                "content": state["draft"]["content"],
                "adaptation_notes": "No adaptation needed for 小红书 mode.",
            }
        else:
            system_prompt = "You adapt content style for different platforms. Return strict JSON."
            user_prompt = (
                f"target_platform={state['platform']}\n"
                f"title={state['draft']['title']}\n"
                f"content={state['draft']['content'][:2500]}\n"
                "Return fields: adapted_content, adaptation_notes."
            )
            try:
                llm = self._call_llm(system_prompt, user_prompt, temperature=0.4)
                usage = llm["usage"]
                parsed = self._extract_json(llm["text"], fallback={})
                state["adapted"] = {
                    "content": parsed.get("adapted_content", llm["text"]),
                    "adaptation_notes": parsed.get(
                        "adaptation_notes", f"Adapted for {state['platform']}"
                    ),
                }
            except Exception as exc:
                error = str(exc)
                state["adapted"] = {
                    "content": state["draft"]["content"],
                    "adaptation_notes": f"adapter fallback due error: {exc}",
                }
        cost = self._estimate_cost(usage["total_tokens"])
        metrics.end(
            "adapter",
            started,
            usage["prompt_tokens"],
            usage["completion_tokens"],
            usage["total_tokens"],
            cost,
            error,
        )
        state["trace"].append("adapter")
        return state

    def node_approval(self, state: Dict[str, Any], metrics: MetricsContext) -> Dict[str, Any]:
        started = metrics.begin("approval")
        decision = state.get("approval_decision", "approve")
        if decision not in {"approve", "reject", "needs_edit"}:
            decision = "approve"
        state["approval"] = {
            "decision": decision,
            "at": _utc_now(),
            "note": state.get("approval_note", ""),
        }
        state["trace"].append("approval")
        metrics.end("approval", started)
        return state

    def node_export(self, state: Dict[str, Any], metrics: MetricsContext) -> Dict[str, Any]:
        started = metrics.begin("export")
        final_body = state["adapted"]["content"] if state.get("adapted") else state["draft"]["content"]
        package = {
            "run_id": state["run_id"],
            "brief": state["brief"],
            "platform": state["platform"],
            "style": state["style"],
            "title": state["draft"]["title"],
            "content": final_body,
            "tags": state["draft"].get("tags", []),
            "review": state["review"],
            "approval": state["approval"],
            "trace": state["trace"],
            "revision_count": state["revision_count"],
            "created_at": _utc_now(),
        }
        out_dir = os.path.join(os.path.dirname(__file__), "..", "outputs")
        os.makedirs(out_dir, exist_ok=True)
        json_path = os.path.join(out_dir, f"{state['run_id']}.json")
        md_path = os.path.join(out_dir, f"{state['run_id']}.md")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(package, f, ensure_ascii=False, indent=2)
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(f"# {package['title']}\n\n")
            f.write(f"- run_id: {package['run_id']}\n")
            f.write(f"- platform: {package['platform']}\n")
            f.write(f"- style: {package['style']}\n")
            f.write(f"- review_score: {package['review']['total_score']}/30\n\n")
            f.write(package["content"])
            f.write("\n\n")
            if package["tags"]:
                f.write(" ".join(package["tags"]))
                f.write("\n")
        state["content_package"] = {
            "json_path": json_path,
            "markdown_path": md_path,
            "title": package["title"],
        }
        state["trace"].append("export")
        metrics.end("export", started)
        return state

    def _initial_state(
        self,
        brief: str,
        platform: str,
        style: str,
        approval_decision: str,
        approval_note: str,
        reviewer_threshold: int,
        max_revisions: int,
        run_id: Optional[str],
    ) -> Dict[str, Any]:
        return {
            "run_id": run_id or uuid.uuid4().hex[:12],
            "brief": brief.strip(),
            "platform": platform,
            "style": style,
            "selected_topic": {"title": brief.strip() or "Untitled topic"},
            "research": {},
            "draft": {},
            "review": {},
            "adapted": {},
            "approval": {},
            "approval_decision": approval_decision,
            "approval_note": approval_note,
            "review_feedback": "",
            "reviewer_threshold": reviewer_threshold,
            "max_revisions": max_revisions,
            "revision_count": 0,
            "status": "running",
            "trace": [],
            "content_package": {},
        }

    def run_workflow(
        self,
        brief: str,
        platform: str = "小红书",
        style: str = "种草推荐",
        approval_decision: str = "approve",
        approval_note: str = "",
        reviewer_threshold: int = 21,
        max_revisions: int = 2,
        run_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        state = self._initial_state(
            brief=brief,
            platform=platform,
            style=style,
            approval_decision=approval_decision,
            approval_note=approval_note,
            reviewer_threshold=reviewer_threshold,
            max_revisions=max_revisions,
            run_id=run_id,
        )
        metrics = MetricsContext()
        self.checkpoint.save(state["run_id"], state, "running")

        state = self.node_research(state, metrics)
        topics = state["research"].get("topics", [])
        if topics:
            state["selected_topic"] = topics[0]
        self.checkpoint.save(state["run_id"], state, "running")

        while True:
            state = self.node_writer(state, metrics)
            state = self.node_reviewer(state, metrics)
            score = int(state["review"].get("total_score", 0))
            if score >= reviewer_threshold:
                break
            if state["revision_count"] >= max_revisions:
                break
            state["revision_count"] += 1
            self.checkpoint.save(state["run_id"], state, "running")

        state = self.node_adapter(state, metrics)
        state = self.node_approval(state, metrics)
        decision = state["approval"]["decision"]
        if decision == "reject":
            state["status"] = "rejected"
            self.checkpoint.save(state["run_id"], state, "rejected")
            return {"run_id": state["run_id"], "state": state, "metrics": metrics.as_dict()}

        if decision == "needs_edit":
            state["status"] = "needs_manual_edit"
            self.checkpoint.save(state["run_id"], state, "needs_manual_edit")
            return {"run_id": state["run_id"], "state": state, "metrics": metrics.as_dict()}

        state = self.node_export(state, metrics)
        state["status"] = "completed"
        self.checkpoint.save(state["run_id"], state, "completed")
        return {"run_id": state["run_id"], "state": state, "metrics": metrics.as_dict()}

    def get_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        return self.checkpoint.load(run_id)

    def list_runs(self, limit: int = 20) -> List[Dict[str, Any]]:
        return self.checkpoint.list_recent(limit=limit)
