# 项目2 Gemini 后台设计结果接入说明

最后更新：2026-04-11

本文件用于收口“后台 / 管理端设计方案”和“当前真实后端能力”的关系。

## 1. 关于 Gemini 3.1 Pro 的核验结论

这份文档里**不能再宣称“已确认实际调用 Gemini 3.1 Pro”**。

已核查事实：
- 本地确实存在 Cursor bridge run 记录，路径位于：
  - `F:\codex\codex1\tools\cursor-bridge\runs\20260411-181502`
- 该 run 的 `meta.json` 中记录了：
  - `model = gemini3.1pro`
  - `agent_kind = wsl`
  - `agent_command = /home/ztk/.local/bin/agent`
- 但进一步核查本机 WSL 中的 Cursor Agent：
  - `agent --list-models` 当前并不包含 Gemini 3.1 Pro

因此，当前最多只能说明：
- 这轮后台设计任务曾通过 Cursor bridge 发起到本机 Cursor Agent
- 但**无法证明最终实际使用的模型就是 Gemini 3.1 Pro**

结论：
- 之前“已实际调用 Gemini 3.1 Pro”的口径不成立
- 本文后续内容只能作为“后台设计接入说明”，不能作为 Gemini 已核验调用的证据

## 2. 后台设计的核心结论

这轮后台设计的有效结论仍然可用，方向是：
- 后台应是“运营与流程控制台”，不是泛化 admin 模板
- 导航应按四类组织：
  - 总览
  - 工作流
  - 质量与资产
  - 系统状态
- 页面重点不应是配置堆叠，而是：
  - 任务怎么发起
  - 运行停在哪里
  - 质检结果如何
  - 系统是否健康

## 3. 与当前真实能力直接匹配的后台模块

可以直接落地或基本直连现有接口的：
- 系统状态页
  - `GET /health`
- 工作流能力页
  - `GET /v2/workflow-capabilities`
- 任务发起页
  - `POST /v2/run`
  - `POST /v2/run/stream`
- 单次运行详情页
  - `GET /v2/runs/{run_id}`
- 引导模式继续页
  - `POST /v2/run/continue`
- 事件探针 / 限流探针
  - `GET /v2/stream-probe`
  - `GET /v2/limit-probe`

## 4. 仍然缺少后端支持的后台模块

当前还不能真正做成完整后台页的：
- 任务列表页
  - 缺 `GET /v2/runs` 列表接口
- 日志检索页
  - 缺日志查询 API
- 审核队列页
  - 目前没有完整“运行中人工审批再提交”后台接口
- 权限与角色页
  - 当前没有认证和 RBAC

## 5. 后台设计稿到真实接口的映射

| 后台页面 / 模块 | 当前真实支持 | 状态 |
|---|---|---|
| 总览看板 | `/health` + 本地最近 run_id | 部分可做 |
| 任务发起 | `/v2/run` / `/v2/run/stream` | 已实现 |
| 单任务详情 | `/v2/runs/{run_id}` | 已实现 |
| 引导继续 | `/v2/run/continue` | 已实现 |
| 系统状态页 | `/health` | 已实现 |
| 能力说明页 | `/v2/workflow-capabilities` | 已实现 |
| 任务列表 | 暂无 | 未实现 |
| 日志页 | 仅文件 `logs/api_v2.jsonl` | 未实现 API 化 |

## 6. 当前后台设计的轻量边界

不应过度承诺的：
- 全量任务管理系统
- 完整 CMS
- 多角色权限后台
- 通用日志大屏
- 复杂配置中心

当前最合理的后台定位仍然是：
**围绕单次工作流运行的运营控制台**

## 7. 下一步最值得补什么

后台下一步最值得补的是：
1. 只读任务列表接口
2. 只读运行日志入口
3. 更明确的审核中心状态页
4. `/demo` 与未来后台页共享的状态组件
