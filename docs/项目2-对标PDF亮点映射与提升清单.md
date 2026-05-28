# 项目2对标 PDF 亮点映射与提升清单

最后更新：2026-04-10

## 使用说明

这份清单只记录两件事：

1. 当前到底已经对齐了哪些 PDF 亮点。
2. 哪些点还只能部分对齐，不能硬写成“已完成”。

## 亮点映射

| PDF 亮点方向 | 当前状态 | 当前证据 | 当前边界 |
|---|---|---|---|
| `LangGraph + SubGraph + PostgreSQL Checkpointer` | 已完成 | `benchmarks/latest_validation_report_v2.json`、`benchmarks/latest_step_plan_runtime_report.json` | 无 |
| 节点级 metrics / token / 时延 | 已完成 | v1/v2 报告、Step Plan 真实链路报告 | 当前成本仍是估算，不是生产账单 |
| `SSE / astream_events` 流式输出 | 已完成（等价对齐） | `/v2/run/stream`、`benchmarks/latest_step_plan_runtime_report.json` | 当前是 token 级 SSE 事件流，但不是 LangGraph 原生 `astream_events` 命名 |
| 指数退避 + 重试 + 熔断 | 已完成 | `src/langgraph_v2/engine.py`、`benchmarks/latest_feature_audit_report.json` | 未做高并发压测 |
| `JSON Mode + 手动解析 + Pydantic` | 已完成 | `src/langgraph_v2/parsers.py`、`benchmarks/latest_step_plan_runtime_report.json` | `Step Plan` 路线当前更多依赖 salvage，不是全 direct |
| `Mock` 开关体系 | 已完成 | `LLM_MOCK / IMAGE_MOCK / CHECKPOINTER_MOCK`、v2 mock 报告 | 图片能力当前只是 mock 预留，没有真实图片流水线 |
| `request_id + 结构化日志` | 已完成 | `logs/api_v2.jsonl`、`logs/engine_v2.jsonl` | 已完成本地结构化日志，不等同于 LangSmith 远端观测 |
| `SlowAPI + /health + graceful shutdown` | 已完成 | `benchmarks/latest_feature_audit_report.json` | 无 |
| `LangSmith` 全链路可观测 | 已完成 | `benchmarks/latest_langsmith_runtime_report.json` | 无 |
| 多模型动态路由 | 未完成 | 无 | 当前仅保留单主模型路线 |
| 并发图片/素材优化 | 未完成 | 无 | 当前仍未进入图片流水线与并发优化 |

## 当前可安全写进简历的亮点

- 基于 `LangGraph` 构建多阶段内容工作流，并通过 `SubGraph` 拆分研究、写作、审核审批。
- 接入 `PostgreSQL Checkpointer` 实现状态持久化与历史回查。
- 通过 `JSON Mode + 手动解析 + Pydantic` 提升关键节点结构化输出稳定性。
- 实现 `/health`、`SlowAPI` 限流、轻量熔断器与优雅关闭。
- 提供 token 级 `SSE` 事件流，并记录 `TTFT`，同时保留 old baseline vs v2 的 before / after 对比报告。
- 增加 `request_id` 与结构化日志，缩短问题排查路径。

## 当前不能硬写的点

- `TTFT` 降低多少
- 多模型动态路由带来的成本下降
- 并发优化带来的吞吐提升

## 下一阶段最值得补的 3 个点

1. 如果还有精力，做多模型路由或并发优化，补结果型指标。
2. 继续压缩 `fenced-salvage` 占比，让结构化输出更接近全 `direct`。
3. 补 `TTFT` 优化前后对比，而不只是捕获数值。
