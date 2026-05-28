# AI 内容运营工作台交付说明

## 可用功能

- 创作工作台：配置 brief、平台、风格、auto/guided、mock/real 图片与视觉质检开关。
- 流程监控：展示运行状态、节点详情、输入摘要、输出摘要、耗时、token、错误、结构化审核。
- 选题决策：guided 模式先暂停，选择候选选题后继续。
- 内容编辑：展示标题、正文、标签，支持按指令重写。
- 图片素材管理：展示封面候选、正文配图、小红书卡片图、总结卡，支持替换并保存到发布清单。
- 发布准备：标题、正文、标签、图片清单、一键复制、图片下载、平台检查、自动发布边界说明。
- 历史回查：读取服务端 run 列表，失败时回退本地缓存。
- 系统管理：健康检查、服务能力、日志、运行查询。

## 平台差异

- 公众号：长文深度表达，1 张封面，3 张正文配图，1 张总结卡。
- 小红书：短笔记/卡片式表达，1 张封面，6 张卡片图，1 张总结卡，标签更丰富。
- 知乎：问答/分析文，1 张封面，1 张解释型配图，1 张总结卡。

平台规则位于 `src/langgraph_v2/platform_rules.py`，生成与发布包会读取规则，不再只靠前端写死。

## 验收命令

Windows 一键验收：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\validate_workbench_local.ps1
```

通过时输出：

```text
WORKBENCH_SMOKE_OK
WORKBENCH_LOCAL_VALIDATE_OK
```

该脚本覆盖：

- `/health`
- `/v2/platform-rules`
- auto 三平台跑通
- guided 选题后继续
- 三平台输出差异
- 图片资产不止封面
- 发布准备包
- 节点详情
- 节点重跑
- SSE final event
- 前端 production build

真实模式就绪检查（不调用模型、不消耗额度）：

```powershell
py scripts\check_real_mode_readiness.py
```

输出 `REAL_MODE_READY` 表示文本、生图、视觉质检和 PostgreSQL 的真实模式环境变量都已打开。

## 启动方式

后端：

```powershell
cd src
py -m uvicorn api_v2:app --host 127.0.0.1 --port 8000
```

前端：

```powershell
cd frontend
npm run dev -- --host 127.0.0.1 --port 5174
```

访问 `http://127.0.0.1:5174/`。

## 风险与后续

- mock 验收已通过；真实 StepFun 文本、真实生图、真实视觉质检需在有额度和 API key 时再跑一轮。
- 节点重跑当前是生成新的可审计 run，不是严格意义上的 checkpoint 单节点续跑。
- 自动发布只交付发布准备包，不保存账号密码、不绕过验证码；仅在平台官方 API 可用时接入。

## 自动发布官方依据

- 微信公众号：优先参考微信公众平台官方开发文档，官方能力覆盖素材、草稿、发布等接口；接入前需确认公众号认证、开发者配置、IP 白名单与权限范围。官方入口：https://developers.weixin.qq.com/doc/offiaccount/Getting_Started/Overview.html
- 小红书：公开可见的官方开放入口主要面向商业/营销场景，自动发布能力不作为默认假设；当前只生成发布准备包，避免 Cookie、模拟登录、绕验证码等违规路径。官方入口：https://ad-market.xiaohongshu.com/
- 知乎：知乎开放平台公开入口偏内容/数据/API/MCP 能力，是否支持账号发文/回答发布需商务或接口权限确认；当前只生成发布准备包。官方入口：https://developer.zhihu.com/
