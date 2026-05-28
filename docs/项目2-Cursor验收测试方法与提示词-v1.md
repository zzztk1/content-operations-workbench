# 项目2-Cursor验收测试方法与提示词-v1

最后更新：2026-04-12

## 1. 目标

让 Cursor 里的 agent 不只是“给建议”，而是对项目2执行一轮真正的验收测试，并输出：

- 通过项
- 失败项
- 风险项
- 证据文件
- 是否达到“可交付 / 可上线 / 可演示”的结论

## 2. 为什么要这样做

项目2现在已经有：

- 本地工作流
- 图片链路
- 视觉质检
- 前后端工作台
- 阿里云公网部署

所以这一步不再适合只做“单点功能验证”，而要做一轮**系统验收**。

Cursor agent 最适合承担的是：

- 重复测试
- 清单式验收
- 结果归档
- 风险枚举

主线程自己只保留：

- 验收范围定义
- 结果判断
- 最终口径收口

## 3. 推荐的验收方法

采用“一主三辅”的验收框架。

### 主验收线程

由一个 Cursor agent 负责统筹：

- 读取项目说明、当前部署状态、现有 benchmark 报告
- 跑一轮验收脚本
- 结合公网入口做功能验证
- 输出总报告

### 三个子方向

1. 服务与部署验收
- `/health`
- `/docs`
- `/demo`
- `/studio`
- `/v2/workflow-capabilities`
- 阿里云公网入口是否正常
- 容器化和部署形态是否自洽

2. 工作流与功能验收
- 文本工作流
- guided / auto 模式
- continue 接口
- 真实/Mock 配图切换
- 视觉质检结果
- run_id 回查

3. 结果与证据验收
- benchmark 文件是否齐全
- 最新报告是否和当前线上状态一致
- 文档和状态文件是否存在口径漂移

## 4. Cursor agent 的工作边界

允许它做：

- 读取代码和文档
- 运行现有 benchmark / smoke
- 调接口做回归
- 修改验收文档
- 新增一份验收总结

不让它默认做：

- 大范围重构
- 随意改动核心业务逻辑
- 修改线上部署配置
- 覆盖已有结论但不提供证据

如果发现阻塞问题，优先顺序应该是：

1. 先确认是验收脚本问题还是项目问题
2. 如果是小修复，直接修并复测
3. 如果是高风险问题，只记录并上报

## 5. 这轮验收的通过标准

至少满足下面这些条件，才能算“项目2验收通过”：

### A. 公网服务通过

- `/health = 200`
- `/docs = 200`
- `/demo = 200`
- `/studio = 200`
- `/v2/workflow-capabilities = 200`

### B. 文本工作流通过

- `/v2/run` 至少完成一次
- `status = completed`
- 返回 `run_id`
- 返回正文
- 返回标题

### C. 图片链路通过

- 能返回主图
- 能返回候选图信息
- 图片字段结构完整

### D. 视觉质检通过

- 返回 `cover_visual_review`
- 有 `overall_score`
- 有 `passed`
- 有 `review_mode`

### E. 历史回查通过

- `GET /v2/runs/{run_id}` 可回查
- 返回 state 快照

### F. 证据链完整

- 最新 benchmark 文件存在
- 当前验收结果落盘
- 结论能对应到证据文件

## 6. Cursor 验收输出格式

要求 Cursor 最终输出：

1. 验收范围
2. 实际执行项
3. 通过项
4. 未通过项
5. 风险项
6. 证据文件路径
7. 最终结论：
   - 通过
   - 有条件通过
   - 不通过

## 7. 直接发给 Cursor 的提示词

下面这段可以直接发给 Cursor `auto` agent：

```md
你现在负责对项目2执行一轮“系统验收测试”，不是做功能设计，也不是做大规模重构。

项目目录：
F:\\codex\\codex1\\projects\\media-agent

你的任务目标：
基于现有代码、现有 benchmark、现有部署结果，对项目2做一轮真实验收，并给出可交付结论。

当前项目背景：
- 项目2是一个自媒体智能内容运营系统
- 已有文本工作流、图片工作流、视觉质检、前后端工作台
- 已部署到阿里云公网
- 当前公网入口：
  - http://47.252.94.172/health
  - http://47.252.94.172/docs
  - http://47.252.94.172/demo
  - http://47.252.94.172/studio

你要做的事情：

1. 先阅读这些文件：
- docs/项目2-模型上线执行清单-v1.md
- docs/项目2-近公网联调与部署说明-v1.md
- docs/项目2-阿里云部署结果-v1.md
- project-memory/projects/project2-status.md

2. 再检查这些 benchmark / 报告：
- benchmarks/latest_deployment_surface_report.json
- benchmarks/latest_aliyun_public_workflow_smoke.json
- benchmarks/latest_feature_audit_report.json
- benchmarks/latest_step_plan_runtime_report.json
- benchmarks/latest_image_asset_quality_report.json
- benchmarks/latest_visual_review_real_report.json

3. 如有必要，重新运行低成本验收：
- 公网 surface 检查
- 一次 `/v2/run` smoke
- 一次 `run_id` 回查

4. 不要做高成本图片大规模压测，除非确有必要

5. 如果发现小问题：
- 可以直接修复并复测
- 但不要进行大规模重构

6. 最终必须输出一份新的验收报告，建议命名为：
- docs/项目2-Cursor验收测试报告-v1.md

报告里必须包含：
- 验收范围
- 实际执行项
- 通过项
- 未通过项
- 风险项
- 证据文件
- 最终结论（通过 / 有条件通过 / 不通过）

通过标准：
- 公网 `/health` `/docs` `/demo` `/studio` `/v2/workflow-capabilities` 都正常
- `/v2/run` 至少成功一次
- 返回标题、正文、run_id
- 图片字段存在
- 视觉质检字段存在
- `GET /v2/runs/{run_id}` 可回查
- 最新结论与证据文件一致

如果所有主链路都通过，请明确给出：
“项目2已达到可交付、可公网演示、可容器化、可验收状态。”
```

## 8. 最推荐的实际使用方式

最稳的方式是：

1. 用 Cursor `auto` agent 跑上面的提示词
2. 让它只做验收，不做大改
3. 主线程最后只审：
- 它的结论
- 它的证据
- 它有没有口径漂移

## 9. 当前结论

这套方法的核心不是“让 Cursor 替我们判断一切”，而是：

> 让 Cursor agent 成为验收执行器和证据整理器，而主线程负责验收范围与最终结论。

