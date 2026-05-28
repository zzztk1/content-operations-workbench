import json

import streamlit as st
from dotenv import load_dotenv

from agent_graph import MediaAgentGraph

load_dotenv()

st.set_page_config(
    page_title="Media Agent Workflow",
    page_icon="🧠",
    layout="wide",
)

st.title("🧠 Media Agent Workflow (Fast-Track)")
st.caption("Stateful workflow: brief -> research -> draft -> review -> approval -> export")

if "engine" not in st.session_state:
    st.session_state.engine = MediaAgentGraph()
if "latest_result" not in st.session_state:
    st.session_state.latest_result = None

engine: MediaAgentGraph = st.session_state.engine

with st.sidebar:
    st.header("Run Config")
    platform = st.selectbox("Platform", ["小红书", "抖音", "微信公众号"], index=0)
    style = st.selectbox("Style", ["种草推荐", "知识科普", "经验分享", "测评对比"], index=0)
    reviewer_threshold = st.slider("Review pass score", 15, 30, 21, 1)
    max_revisions = st.slider("Max revisions", 0, 4, 2, 1)
    approval = st.selectbox("Approval decision", ["approve", "needs_edit", "reject"], index=0)
    approval_note = st.text_input("Approval note (optional)", "")
    st.markdown("---")
    st.caption("Tip: set `LLM_MOCK=true` in .env for local no-key testing.")

tab_run, tab_runs = st.tabs(["Run Workflow", "Run History"])

with tab_run:
    brief = st.text_area(
        "Content brief",
        placeholder="例如：围绕 AI 产品经理求职，生成一篇小红书风格的避坑指南",
        height=120,
    )

    if st.button("Start workflow", type="primary", disabled=not brief.strip()):
        with st.spinner("Running workflow..."):
            result = engine.run_workflow(
                brief=brief,
                platform=platform,
                style=style,
                approval_decision=approval,
                approval_note=approval_note,
                reviewer_threshold=reviewer_threshold,
                max_revisions=max_revisions,
            )
        st.session_state.latest_result = result

    if st.session_state.latest_result:
        result = st.session_state.latest_result
        state = result["state"]
        metrics = result["metrics"]

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Run ID", state["run_id"])
        c2.metric("Status", state["status"])
        c3.metric("Review Score", f"{state.get('review', {}).get('total_score', 0)}/30")
        c4.metric("Revisions", str(state.get("revision_count", 0)))

        st.subheader("Workflow Trace")
        st.write(" -> ".join(state.get("trace", [])))

        st.subheader("Generated Content")
        draft = state.get("draft", {})
        st.markdown(f"### {draft.get('title', 'Untitled')}")
        st.write(state.get("adapted", {}).get("content") or draft.get("content", ""))
        tags = draft.get("tags", [])
        if tags:
            st.caption(" ".join(tags))

        st.subheader("Review")
        review = state.get("review", {})
        rc1, rc2, rc3, rc4 = st.columns(4)
        rc1.metric("Attraction", review.get("attraction_score", 0))
        rc2.metric("Accuracy", review.get("accuracy_score", 0))
        rc3.metric("Platform", review.get("platform_score", 0))
        rc4.metric("Total", review.get("total_score", 0))
        st.info(review.get("feedback", ""))

        st.subheader("Metrics")
        totals = metrics.get("totals", {})
        mc1, mc2, mc3, mc4 = st.columns(4)
        mc1.metric("Latency (ms)", totals.get("latency_ms", 0.0))
        mc2.metric("Total Tokens", totals.get("total_tokens", 0))
        mc3.metric("Est. Cost (USD)", totals.get("estimated_cost_usd", 0.0))
        mc4.metric("Errors", totals.get("error_count", 0))

        with st.expander("Node Metrics (JSON)", expanded=False):
            st.code(json.dumps(metrics.get("node_metrics", []), ensure_ascii=False, indent=2))

        with st.expander("Export Package", expanded=False):
            st.code(json.dumps(state.get("content_package", {}), ensure_ascii=False, indent=2))

with tab_runs:
    st.subheader("Recent Runs")
    runs = engine.list_runs(limit=30)
    if not runs:
        st.info("No runs yet.")
    else:
        st.dataframe(runs, use_container_width=True)
        selected_run = st.selectbox("Load run", [r["run_id"] for r in runs])
        if st.button("Load selected run"):
            loaded = engine.get_run(selected_run)
            if loaded:
                st.success(f"Loaded run {selected_run} ({loaded['status']})")
                with st.expander("Saved state JSON"):
                    st.code(json.dumps(loaded["state"], ensure_ascii=False, indent=2))
