# 项目2-发Gemini的项目总说明-v1

## 1. 项目概况

这是一个“智能内容运营系统”，不是聊天机器人，也不是单点 AI 写作工具。

它的目标是把内容生产流程做成一条可运行、可恢复、可回查、可观测的工作流，覆盖：

- brief intake
- research
- writer
- review
- approval
- cover planning
- image generation
- visual review
- export

项目当前技术基座：

- 后端框架：FastAPI
- 工作流框架：LangGraph
- 状态持久化：PostgreSQL Checkpointer
- 文本模型：StepFun `step-3.5-flash`
- 图片模型：StepFun `step-2x-large`
- 视觉质检模型：StepFun `step-1o-turbo-vision`
- 流式输出：SSE
- 观测：LangSmith + 结构化日志 + request_id

这个项目不是“问一句答一句”，而是一个 AI 内容工作流系统。

## 2. 当前业务流程

当前主链路大致是：

1. brief intake
2. research_topic
3. research_evidence_merge
4. write_draft
5. adapt_platform
6. plan_cover
7. generate_cover
8. review_cover_visual
9. review_structured
10. review_route
11. approval_gate
12. export

支持两种运行模式：

- `auto`
  - 从 research 直接跑到 export
- `guided`
  - research 后先停下，给用户候选选题
  - 用户选题后，再继续跑完整链路

## 3. 当前已经有的核心功能

### 文本相关

- 根据 brief 生成内容方向和候选选题
- 生成公众号 / 小红书 / 知乎等平台适配内容
- 结构化审核
- 低分重写
- 审批决策
- 多格式导出

### 图片相关

- 根据文章生成封面策划
- 真实封面图生成
- 多候选图生成
- 主图与候选图导出
- 图文一致性轻量检查
- 视觉模型级封面质检

### 系统相关

- `/health` 健康检查
- `/v2/run` 同步运行
- `/v2/run/stream` 流式运行
- `/v2/run/continue` 引导模式继续运行
- `/v2/runs/{run_id}` 结果回查
- SlowAPI 限流
- graceful shutdown
- request_id 全链路关联
- LangSmith tracing
- 结构化日志

## 4. 当前前端真实存在的问题

Gemini 这次重构前端时，必须优先解决这些问题：

1. 当前页面整体更像“接口测试台”，不像“工作流产品”
2. 正文展示不稳定，容易出现“只有标题没有正文”的错误体验
3. 图片区域太抢眼，容易压住正文存在感
4. guided 模式的候选选题体验不够产品化
5. mock / real 状态不够醒目
6. 页面有中文乱码和展示层细节问题
7. 交付预览、运行指标、开发者抽屉之间层级关系不够清晰

## 5. 这次前端重构最关键的目标

请优先解决：

1. 让正文稳定显示
2. 让标题、正文、标签、主图、候选图关系合理
3. 让页面更像“AI 内容工作流操作台”
4. 让 guided 模式更像“流程决策点”
5. 让 mock / real 状态清晰可见
6. 不改后端协议前提下，完成产品级重构

## 6. 当前后端已定、不要乱改的接口

### 6.1 健康检查

#### `GET /health`

用途：

- 查看服务状态
- 查看当前文本模型、图片模型、视觉模型
- 查看 PostgreSQL 是否连通
- 查看当前 mock / real 状态

典型返回信息包括：

- `status`
- `llm_model`
- `llm_provider_route`
- `image_model`
- `image_mock`
- `vision_model`
- `vision_review_mock`
- `checkpoint_backend`
- `checks.postgres_connectivity`

### 6.2 能力说明

#### `GET /v2/workflow-capabilities`

用途：

- 告诉前端有哪些运行模式
- 告诉前端有哪些导出格式
- 告诉前端有哪些核心 endpoint

### 6.3 同步运行

#### `POST /v2/run`

请求主要字段：

- `brief`
- `platform`
- `style`
- `run_mode`
- `export_formats`
- `approval_decision`
- `approval_note`
- `reviewer_threshold`
- `max_revisions`
- `image_mock`
- `cover_candidate_count`
- `vision_review_mock`

返回核心包括：

- `run_id`
- `request_id`
- `status`
- `state`
- `metrics`

### 6.4 流式运行

#### `POST /v2/run/stream`

通过 SSE 返回事件。

事件包括：

- `start`
- `token`
- `token_summary`
- `update`
- `final`
- `error`

这条接口是前端流式体验的核心。

### 6.5 引导模式继续

#### `POST /v2/run/continue`

用途：

- 在 `guided` 模式下，用户选完 research 候选题后继续执行后续流程

请求核心字段：

- `run_id`
- `selected_topic_index`
- `approval_decision`
- `approval_note`
- `reviewer_threshold`
- `max_revisions`
- `image_mock`
- `cover_candidate_count`
- `vision_review_mock`
- `export_formats`

### 6.6 单次运行回查

#### `GET /v2/runs/{run_id}`

用途：

- 根据 `run_id` 回查完整 state
- 用于 guided 模式继续前加载候选选题
- 用于查看最终工作流结果

## 7. 当前前端真正需要展示的内容

### 7.1 左侧任务配置区

建议展示：

- brief
- platform
- style
- run_mode
- export_formats
- reviewer_threshold
- max_revisions
- approval_decision
- approval_note
- image mode: default / real / mock
- cover_candidate_count
- vision review mode: default / real / mock

### 7.2 中间交付预览区

必须展示：

- 标题
- 正文
- 标签
- 主图
- 候选图
- 视觉质检摘要
- 图文一致性摘要

重要要求：

- 正文优先级高于图片
- 图片是交付的封面资产，不应压倒正文

### 7.3 右侧流程追踪区

建议展示：

- run status
- run_id
- request_id
- TTFT
- 当前阶段
- 已完成节点列表

### 7.4 二级开发者区

建议做成折叠 / tab / drawer：

- raw events
- metrics json
- health snapshot

不要抢首屏。

## 8. 当前结果对象里前端最应该读的字段

Gemini 做页面时，展示逻辑建议以这些字段为主。

### 标题

优先级建议：

1. `result.state.adapted.title`
2. `result.state.draft.title`
3. `result.state.content_package.title`
4. `result.state.title`
5. `result.title`

### 正文

优先级建议：

1. `result.state.adapted.content`
2. `result.state.draft.content`
3. `result.state.content_package.content`
4. `result.state.content`
5. `result.content`

### 标签

优先级建议：

1. `result.state.adapted.tags`
2. `result.state.draft.tags`
3. `result.state.content_package.tags`
4. `result.state.tags`
5. `result.tags`

### 主图

优先级建议：

1. `result.state.image_asset.web_path`
2. `result.state.image_asset.image_url`
3. `result.state.content_package.image_web_path`
4. `result.state.content_package.image_url`

### 候选图

主要来自：

- `result.state.cover_candidates`
- 或 `result.state.content_package.cover_candidates_summary`

### 视觉质检

主要来自：

- `result.state.cover_visual_review`
- 或 `result.state.content_package.cover_visual_review`

### 图文一致性

主要来自：

- `result.state.text_image_consistency`
- 或 `result.state.content_package.text_image_consistency`

## 9. 当前前端必须注意的约束

Gemini 设计和实现时，必须遵守这些约束：

1. 不要把页面做成聊天页面
2. 不要改后端接口协议
3. 不要删掉图片、多候选图、视觉质检、guided 模式
4. 不要假设后端会新增很多字段
5. 必须优先解决“正文稳定显示”
6. 必须明确 mock / real 状态
7. 页面必须是正常中文，不允许乱码风格文案

## 10. 这次希望 Gemini 输出什么

请让 Gemini 输出：

1. 页面信息架构
2. 前后端字段映射表
3. 关键交互说明
4. 视觉风格建议
5. 最好直接输出一版可替换 `demo_v2.html` 的 HTML / CSS / JS 实现

## 11. 你可以直接发给 Gemini 的一句话补充

“这次不要帮我重新发明后端，也不要把它改成聊天产品。请只基于现有接口，把页面重构成一个真正的 AI 内容工作流操作台，优先解决正文不稳定、图片压正文、guided 模式不产品化、mock 状态不明显这几个真实问题。”
