# 工作台验收矩阵

## 前端产品化

- 创作工作台、流程监控、选题决策、内容编辑、图片素材、发布准备、历史回查、系统管理：由 React 工作台提供，入口 `frontend/src/App.tsx` 与 `frontend/src/components/CreatorStudio.tsx`。
- 页面真实调用后端：API 封装位于 `frontend/src/lib/mediaAgentApi.ts`，调用 `/health`、`/v2/run`、`/v2/run/stream`、`/v2/run/continue`、`/v2/runs`、`/v2/runs/{run_id}`、`/v2/runs/{run_id}/nodes`、`/v2/run/rewrite`、`/v2/platform-rules`。
- 前端可启动：`scripts/validate_workbench_local.ps1` 会启动 Vite 并验证 HTTP 200。

## 工作流可控

- 节点详情：`GET /v2/runs/{run_id}/nodes` 返回状态、输入摘要、输出摘要、耗时、token、错误。
- 停止运行：`POST /v2/runs/{run_id}/stop`，引擎支持边界协作式取消。
- 重写：`POST /v2/run/rewrite`。
- 节点重跑：`POST /v2/runs/{run_id}/nodes/{node}/rerun`，当前实现为新建可审计 rerun，不覆盖原 run。
- guided 选题暂停/继续：`/v2/run` 的 `guided` 模式返回 `awaiting_topic_selection`，再用 `/v2/run/continue` 继续。

## 平台适配

- 配置化规则：`src/langgraph_v2/platform_rules.py`。
- 输出差异：`src/langgraph_v2/engine.py` 的平台适配会区分正文结构、标签数量、图片目标。
- 验收脚本验证：公众号 5 图、小红书 8 图、知乎 3 图，且三平台正文前缀不同。

## 图片能力

- 支持封面、正文配图、卡片图、总结卡/金句卡。
- 支持 mock/real 切换、多候选封面、并发生成、失败重试、视觉质检。
- 前端可查看、选择、替换图片，并通过 `PATCH /v2/runs/{run_id}/publish-overrides` 保存到发布清单。

## 发布准备

- 发布包包含标题、正文、标签、图片清单、复制块、平台检查、手动步骤、自动发布边界说明。
- 不保存账号密码，不绕过验证码；仅在官方 API 可用时接入自动发布。
- 官方依据记录在 `docs/WORKBENCH_DELIVERY.md`。

## 本地验收

运行：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\validate_workbench_local.ps1
```

通过信号：

```text
WORKBENCH_SMOKE_OK
FRONTEND_DEV_SERVER_OK
WORKBENCH_LOCAL_VALIDATE_OK
```

## 已知风险

- 真实 StepFun 文本、生图、视觉质检未在最终验收脚本中消耗额度重跑。
- 节点重跑是审计式新 run，不是严格 checkpoint 单节点原地续跑。
- 自动发布仍是发布准备包，未接入平台账号发布。
