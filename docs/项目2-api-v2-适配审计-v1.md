# 项目2 · api_v2 前后端适配审计（v1）

最后更新：2026-04-11

## 1. 路由契约（不得破坏）

以下路由为稳定面：`GET /health`、`GET /demo`、`POST /v2/run`、`POST /v2/run/stream`、`GET /v2/runs/{run_id}`。扩展均为可选字段或新路由，不改变既有成功响应形状。

## 2. `WorkflowRunRequest` 与引擎

| 字段 | 作用 | 引擎消费 |
|------|------|-----------|
| `brief` … `max_revisions` | 任务与审核参数 | `_initial_state` |
| `run_id` | 可选自定义 run / thread | `run_workflow` / checkpoint |
| `image_mock`、`cover_candidate_count`、`vision_review_mock` | 运行时覆盖 | `runtime_flags` / 封面数量 |
| `run_mode` | `auto` / `guided` | `_initial_state` 中 `run_mode`、`guided_topic_locked` |
| `export_formats` | `json` / `md` / `txt` / `html`（及别名 markdown、text） | `node_export` 按格式写文件 |

无效 `run_mode` 返回 **422**。

## 3. 引导继续：`POST /v2/run/continue`

**推荐**请求体仅含 `run_id` + `selected_topic_index`（及可选覆盖项），服务端用 `GET` 等价逻辑从 checkpointer 读取 `state`，再调用 `LangGraphMediaAgentEngine.run_workflow_continue`。

- 若快照不存在：**404** `run not found`。
- 若 `status != awaiting_topic_selection`：**400**。
- 仍支持传入完整 `state`（旧客户端兼容）；与 `run_id` 同时存在时以 **`run_id` 为准**。

## 4. 能力清单：`GET /v2/workflow-capabilities`

静态 JSON：支持的 `run_modes`、各导出格式是否实现、DOCX/PDF 为 reserved、相关端点路径。无密钥、无环境依赖，便于前端与集成方对齐。

## 5. 实现 vs 占位

| 项 | 状态 |
|----|------|
| `/v2/run`、`/v2/run/stream` 传 `run_mode` / `export_formats` | **已实现** |
| `/v2/run/continue` + `run_id` | **已实现**（引擎 `run_workflow_continue`） |
| `/v2/workflow-capabilities` | **已实现**（说明性） |
| DOCX/PDF 导出 | **未实现**（能力与演示页均为占位） |
