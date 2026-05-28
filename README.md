# Media Agent (Project 2 Complete Delivery v1)

项目2当前目标：交付可验证、可演示、可持续迭代的内容运营 Agent 工作台闭环资产。

## 页面预览

![创作工作台](docs/screenshots/workbench-creator.png)

![历史回查](docs/screenshots/workbench-history.png)

## 当前已实现能力

- 旧版 baseline：状态机 + SQLite checkpoint + Streamlit / CLI
- 新版 v2：`LangGraph StateGraph + SubGraph + PostgreSQL Checkpointer`
- 真实模型线路：阶跃星辰 `Step Plan`
- 审核重写闭环：评分低于阈值时自动重写（可配置最大重写次数）
- 人工审批分支：`approve / needs_edit / reject`
- 结构化输出：`JSON Mode / 手动解析 / Pydantic`
- 服务治理：`/health`、`SlowAPI`、轻量熔断器、优雅关闭
- 流式能力：token 级 `SSE` 事件流 + `TTFT` 捕获
- 结构化日志：API / engine 双 JSONL 日志 + `request_id`
- 封面视觉质检：`review_cover_visual` 节点，StepFun 视觉模型（默认 `step-1o-turbo-vision`），支持 `VISION_REVIEW_MOCK` 与请求体 `vision_review_mock` 覆盖
- 测量材料：v1/v2 报告、before/after 对比、Step Plan 真实链路报告、功能审计报告、视觉质检 mock / real / badcase 报告

## 快速开始

```bash
cd F:\codex\codex1\projects\media-agent
pip install -r requirements.txt
copy .env.example .env
```

`.env` 关键项：

```env
STEPFUN_API_KEY=your-api-key
STEPFUN_API_BASE=https://api.stepfun.com/step_plan/v1
STEPFUN_MODEL=step-3.5-flash
STEPFUN_IMAGE_API_KEY=
STEPFUN_IMAGE_API_BASE=https://api.stepfun.com/v1
STEPFUN_IMAGE_MODEL=step-2x-large
STEPFUN_IMAGE_SIZE=1024x1024
STEPFUN_IMAGE_QUALITY=standard
STEPFUN_VISION_API_KEY=
STEPFUN_VISION_API_BASE=https://api.stepfun.com/v1
STEPFUN_VISION_MODEL=step-1o-turbo-vision
VISION_REVIEW_MOCK=true
POSTGRES_DSN=postgresql://postgres:postgres@127.0.0.1:65432/media_agent
LANGSMITH_TRACING=false
LANGSMITH_TRACING_V2=false
LANGSMITH_ENDPOINT=https://api.smith.langchain.com
LANGSMITH_WORKSPACE_ID=
LANGSMITH_PROJECT=media-agent-v2
LLM_MOCK=false
CHECKPOINTER_MOCK=false
ENABLE_JSON_MODE=false
ENABLE_SLOWAPI=true
LLM_CIRCUIT_BREAKER_THRESHOLD=3
LLM_CIRCUIT_BREAKER_COOLDOWN_SEC=30
LLM_MAX_RETRIES=2
LLM_RETRY_BACKOFF_BASE_SEC=0.8
```

当前默认走阶跃星辰 `Step Plan` 路线；如果你看到 `/health` 里的 `llm_provider_route=step_plan`，说明已经切对线路。  
本地快速验证可设 `LLM_MOCK=true`。

## 运行方式

UI：

```bash
cd src
streamlit run main.py
```

CLI：

```bash
cd src
python run_workflow.py --brief "AI Agent 在内容运营中的真实应用场景" --platform 小红书 --style 种草推荐
```

LangGraph v2 CLI（并行 MVP 链路）：

```bash
cd src
py run_workflow_v2.py --brief "AI Agent 在内容运营中的真实应用场景" --platform 小红书 --style 种草推荐
```

LangGraph v2 API（含 `/health`、SlowAPI 限流、轻量熔断器、优雅关闭）：

```bash
cd src
py -m uvicorn api_v2:app --host 127.0.0.1 --port 8000
```

React 内容运营工作台：

```bash
cd frontend
npm install
npm run dev -- --host 127.0.0.1 --port 5174
```

访问 `http://127.0.0.1:5174/`。Vite 会把 `/health`、`/v2`、`/outputs` 代理到本地 API。工作台包含创作、监控、选题、编辑、素材、发布、历史和系统管理视图。

完整交付说明见 `docs/WORKBENCH_DELIVERY.md`；逐项验收证据见 `docs/WORKBENCH_ACCEPTANCE.md`。

LangGraph v2 SSE 事件流（token 级事件流 + 图级更新）：

```bash
curl -N -X POST http://127.0.0.1:8000/v2/run/stream ^
  -H "Content-Type: application/json" ^
  -d "{\"brief\":\"AI Agent 在内容运营中的真实应用场景\",\"platform\":\"小红书\",\"style\":\"种草推荐\"}"
```

如果只是本地验证新版 graph，可以先设置：

```env
LLM_MOCK=true
CHECKPOINTER_MOCK=true
```

一键 mock 验收工作台后端能力：

```bash
set PYTHONPATH=src
set LLM_MOCK=true
set IMAGE_MOCK=true
set VISION_REVIEW_MOCK=true
set CHECKPOINTER_MOCK=true
set CHECKPOINT_BACKEND=memory
py scripts\validate_workbench_smoke.py
```

通过时会输出 `WORKBENCH_SMOKE_OK`。该脚本覆盖健康检查、三平台自动模式、平台差异、图片资产、发布准备包、guided 继续、节点详情、节点重跑和 SSE final 事件。

如果要验证真实 StepFun Step Plan + PostgreSQL 链路，则需要补齐：

```env
STEPFUN_API_KEY=...
STEPFUN_API_BASE=https://api.stepfun.com/step_plan/v1
STEPFUN_MODEL=step-3.5-flash
STEPFUN_IMAGE_API_KEY=...
STEPFUN_IMAGE_API_BASE=https://api.stepfun.com/v1
STEPFUN_IMAGE_MODEL=step-2x-large
STEPFUN_VISION_API_KEY=...
STEPFUN_VISION_API_BASE=https://api.stepfun.com/v1
STEPFUN_VISION_MODEL=step-1o-turbo-vision
VISION_REVIEW_MOCK=false
POSTGRES_DSN=postgresql://...
CHECKPOINTER_MOCK=false
IMAGE_MOCK=false
```

真实视觉质检（非 mock）需同时：`VISION_REVIEW_MOCK=false`、可用的 `STEPFUN_VISION_API_KEY`（或复用已配置的 StepFun key）、以及可被视觉 API 读取的栅格图（如 PNG）；详见 `docs/项目2-视觉质检收口总结-v1.md`。

如果你想排查是否误走了普通按量 API，可以访问：

```bash
curl http://127.0.0.1:8000/health
```

重点看这几个字段：
- `llm_provider_route`
- `llm_api_base`
- `llm_model`
- `image_model`（默认正式基线为 `step-2x-large`）
- `vision_model`、`vision_review_mock`、`vision_client_available`、`checks.vision_configured`

本地 PostgreSQL 启停脚本：

```bash
powershell -ExecutionPolicy Bypass -File scripts\start_local_postgres.ps1
powershell -ExecutionPolicy Bypass -File scripts\stop_local_postgres.ps1
```

API 健康检查：

```bash
curl http://127.0.0.1:8000/health
```

API 运行 workflow：

```bash
curl -X POST http://127.0.0.1:8000/v2/run ^
  -H "Content-Type: application/json" ^
  -d "{\"brief\":\"AI Agent 在内容运营中的真实应用场景\",\"platform\":\"小红书\",\"style\":\"种草推荐\"}"
```

## 自动验证与演示材料

- 自动验证脚本：`benchmarks/validate_workflow.py`
- 验证报告：`benchmarks/latest_validation_report.json`
- before/after 对比脚本：`benchmarks/compare_workflow_versions.py`
- 对比报告：`benchmarks/latest_compare_report.json`
- Step Plan 真实链路校验脚本：`benchmarks/validate_step_plan_runtime.py`
- Step Plan 真实链路报告：`benchmarks/latest_step_plan_runtime_report.json`
- LangSmith 真实校验脚本：`benchmarks/validate_langsmith_runtime.py`
- LangSmith 真实校验报告：`benchmarks/latest_langsmith_runtime_report.json`
- 功能审计脚本：`benchmarks/audit_feature_coverage.py`（含图片能力矩阵、`image_artifacts` 与 `step-2x-large` 性能基线行）
- 默认图片模型正式基线汇总（不调用图片 API，从既有 JSON 生成）：`benchmarks/build_image_performance_baseline.py` → `benchmarks/latest_image_performance_baseline.json`
- 视觉质检：`benchmarks/validate_visual_review_mock.py`、`benchmarks/validate_visual_review_real.py`（低成本，复用已有 PNG）、`benchmarks/validate_visual_review_badcase.py` → `benchmarks/latest_visual_review_*_report.json`
- 图片结果文件快速校验（不调用图片 API）：`benchmarks/validate_image_audit_artifacts.py`
- 视觉质检收口说明：`docs/项目2-视觉质检收口总结-v1.md`
- 功能审计报告：`benchmarks/latest_feature_audit_report.json`
- 演示手册：`docs/工作流验证与演示手册.md`
- 功能审计与修复清单：`docs/项目2-功能审计与修复清单-v1.md`
- PDF亮点映射：`docs/项目2-对标PDF亮点映射与提升清单.md`
- 最终完成度清单：`docs/项目2最终完成度清单-v2.md`
- 工程化交付说明：`docs/工程化交付说明-v1.md`

运行自动验证：

```bash
python benchmarks\validate_workflow.py
```

运行 LangGraph v2 验证：

```bash
py benchmarks\validate_workflow_v2.py
```

运行 baseline vs LangGraph v2 对比：

```bash
py benchmarks\compare_workflow_versions.py
```

运行 Step Plan 真实链路校验：

```bash
py benchmarks\validate_step_plan_runtime.py
```

运行功能审计：

```bash
py benchmarks\audit_feature_coverage.py
```

当前日志文件：

- `logs/api_v2.jsonl`
- `logs/engine_v2.jsonl`
