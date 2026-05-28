# 项目2 · demo_v2 前后端适配审计（v1）

最后更新：2026-04-11

## 1. 页面职责

`GET /demo` 返回内嵌的 `src/demo_v2.html`，用于在浏览器中验证 LangGraph v2 工作流：健康检查、同步/流式运行、Run 回查、引导模式选题与继续。

## 2. 与真实能力对齐情况

| 能力 | 后端事实来源 | 演示页行为 |
|------|----------------|------------|
| 健康检查 | `GET /health` | 顶部五条：服务状态、文本模型、图片模式、流程存档（checkpoint 后端）、视觉质检 |
| 自动模式 | `POST /v2/run` body 字段 `run_mode: "auto"`（默认） | 「运行模式」选「自动」 |
| 引导模式 | 引擎在 `run_mode: "guided"` 时于研究后暂停，`status: awaiting_topic_selection` | 选「引导」；暂停后展示候选选题，「选题后继续」调用 `POST /v2/run/continue` |
| 导出格式 | `export_formats` 经引擎 `_normalize_export_formats`；落地文件为 `.v2.json` / `.v2.md` / `.v2.txt` / `.v2.html` | 多选 JSON、Markdown、TXT、HTML；DOCX/PDF 为禁用占位 |
| 流式事件 | `POST /v2/run/stream`（SSE） | 「开始流式运行」；若引导暂停则 `GET /v2/runs/{run_id}` 补全选题数据 |
| 同步结果 | `POST /v2/run` | 「同步运行」 |
| Run 快照 | `GET /v2/runs/{run_id}` | 提示与开发者抽屉中的事件并列存在 |

## 3. 已知限制（非缺陷）

- 流式结束时的 `final` 事件可能不包含完整 `research`，引导暂停时会再请求 `/v2/runs/{run_id}` 刷新选题列表。
- DOCX/PDF 仅 UI 占位，与 `GET /v2/workflow-capabilities` 中 `reserved` 声明一致。

## 4. 本轮改动摘要（若需追溯）

- 运行模式、导出多选、引导选题区、继续按钮与 `/v2/run/continue`（`run_id` 方式）对齐。
- 暂停态下交付预览区文案改为「等待选题」，避免空白正文误导。
