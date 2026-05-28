# 项目2 · 后端/管理端设计（Gemini 3.1 Pro 任务对齐 · v1）

最后更新：2026-04-11

本文档在 **project2 当前真实后端**（`src/api_v2.py`）与 LangGraph v2 引擎能力范围内，描述「运营型管理端」的信息架构、导航与页面要点，并标明 **现可落地 / 需另补后端** 的边界。  
与 `docs/项目2-Gemini3.1Pro-设计集成-v1.md` 分工：**本文偏管理端功能与 API 映射**；设计集成文档偏体验与线框级布局。

---

## 1. 关于 Gemini 3.1 Pro 与可核验性

- 若任务在 Cursor/CLI 中以 `--model` 指向 **Gemini 3.1 Pro**（或等价），产品意图可为使用该模型产出设计类内容。  
- **本仓库不记录**外部 LLM 调用的模型名、请求 ID 或 token，故**无法仅从 Git 或代码证明**某次文档一定由 Gemini 3.1 Pro 生成。  
- 本文内容根据 **`api_v2.py`、`langgraph_v2/engine.py` 与 `docs/` 下项目2 适配文档**整理；合规留痕请在所用平台或网关侧保留审计日志。

---

## 2. 管理端定位与信息架构

定位：**内容工作流运营控制台**——配置 Brief、观测流水线阶段、处理引导模式暂停与选题继续、查看质检与导出；**不是**通用多租户后台、也不是即时聊天。

四层信息模型（与现 API 一致）：

| 层级 | 管理端职责 | 真实后端 |
|------|------------|----------|
| 运行环境态势 | 可用性、LLM/配图/视觉路线、checkpoint、限流、关停 | `GET /health`（含 `status`、`checks.*`、`shutting_down`） |
| 任务与策略 | Brief、平台、风格、`run_mode`、`export_formats`、审核阈值、配图与视觉覆盖 | `POST /v2/run`、`POST /v2/run/stream`；说明见 `GET /v2/workflow-capabilities` |
| 单次运行与交付 | `run_id`、`trace`、交付物、引导态选题 | 响应 `state`；`GET /v2/runs/{run_id}`；`POST /v2/run/continue` |
| 排障与审计 | HTTP 结构化日志 | `logs/api_v2.jsonl`；响应头 `X-Request-ID`；**无**日志查询 API |

**原则**：无列表类 API 时，不虚构「全库任务历史」；最近 Run ID 由客户端本地保存或人工输入。

---

## 3. 建议导航（一级）

| 分组 | 导航项 | 对应能力 |
|------|--------|----------|
| 总览 | 控制台 / 仪表板 | `GET /health`；快捷发起；最近 Run ID（本地） |
| 工作流 | 任务发起 | `WorkflowRunRequest` 全字段 |
| 工作流 | 运行快照与引导继续 | `GET /v2/runs/{run_id}`；`awaiting_topic_selection` 时 `POST /v2/run/continue` |
| 观测 | 流程追踪 | `state.trace`；SSE `update` / `final` |
| 质量 | 审核与质检 | `state` 只读展示；审批参数在**发起/继续请求体** |
| 资产 | 导出与静态资源 | capabilities；`outputs/` → `GET /outputs/...` |
| 系统 | 系统状态 | 整页 `/health` |
| 系统 | 排障 | JSONL 路径、`X-Request-ID` 关联说明 |

**一期非目标**：用户/角色管理、菜单配置器、通用报表工厂（无认证 API 前均不承诺）。

---

## 4. 页面要点（线框级）

### 4.1 仪表板

- 顶栏：`status`（含 `degraded`）、`graph_version`、`checks.llm_configured` / `image_configured` / `vision_configured` / `postgres_connectivity`。  
- `shutting_down === true` 时：除 `/health` 外可能 **503**（中间件）。  
- 最近运行：无列表 API → `localStorage` 或粘贴 `run_id` → `GET /v2/runs/{run_id}`。

### 4.2 任务发起

- 字段与 `WorkflowRunRequest` 一致（含 `run_mode`、`export_formats`、`run_id` 可选等）。  
- 同步：`POST /v2/run`；流式：`POST /v2/run/stream`（仅当 `enable_sse` 为真，否则 **404**）。  
- 引导：`state.status === awaiting_topic_selection` 时展示选题与继续入口。

### 4.3 流程追踪

- 主数据：`state.trace`；流式合并 SSE。  
- 演示页 `demo_v2` 对节点名做**中文映射展示**；集成方若自建 UI，建议同样对用户展示中文阶段名。

### 4.4 审核与质检

- 只读展示 `state` / `content_package` 中与引擎一致的键（如 `cover_visual_review`）。  
- 无「运行中独立改批注再审」专用 API 时，UI 不得暗示完整 HITL 已存在。

### 4.5 导出与文件

- 以 `GET /v2/workflow-capabilities` 为准：`json`/`md`/`txt`/`html` 已实现；`docx`/`pdf` 为 reserved。  
- 引擎落盘于 `outputs/`，应用挂载 `/outputs`。

### 4.6 日志

- 现实：仅文件 JSONL，无查询 API；一期说明路径与 `grep`/集中日志方案。

---

## 5. 映射表：模块 → API → 可落地 vs 依赖

| 模块 | 当前 API / 支撑 | 现可落地 | 依赖 |
|------|-----------------|----------|------|
| 环境态势 | `GET /health` | 是 | 无 |
| 能力说明 | `GET /v2/workflow-capabilities` | 是 | 无 |
| 同步运行 | `POST /v2/run` | 是 | 无 |
| 流式运行 | `POST /v2/run/stream` | 依赖 `enable_sse` | 配置或 UI 降级 |
| 引导继续 | `POST /v2/run/continue` | 是 | 无 |
| 运行快照 | `GET /v2/runs/{run_id}` | 是 | 无 |
| 限流探针 | `GET /v2/limit-probe` | 是 | 无 |
| SSE 探针 | `GET /v2/stream-probe` | 依赖 `enable_sse` | 同流式 |
| 演示页 | `GET /demo` | 是 | 无 |
| 任务列表 / 搜索 | **无** | 否 | 新 API 或外部存储 |
| 登录 / RBAC | **无** | 否 | 认证授权 |
| 服务端日志 UI | JSONL | 否 | 只读 API 或 ELK |
| DOCX/PDF | reserved | 占位 | 引擎扩展 |

---

## 6. 低风险后续步骤

1. 独立前端路由承载上表导航，**不修改**稳定 JSON 契约（见 `项目2-api-v2-适配审计-v1.md`）。  
2. 系统状态页：对 `degraded`、`postgres_connectivity`、`llm_circuit_breaker` 做告警样式与中文化。  
3. 流式按钮：`enable_sse=false` 时禁用并提示。  
4. 最近 Run：`localStorage` 记录若干 `run_id`。  
5. 排障：展示最近响应 `X-Request-ID`。

---

## 参考

- `src/api_v2.py`  
- `docs/项目2-api-v2-适配审计-v1.md`  
- `docs/项目2-前后端页面与接口对齐表-v1.md`  
- `docs/项目2-前后端适配缺口清单-v1.md`  
