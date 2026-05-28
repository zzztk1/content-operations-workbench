# 项目2 Cursor 与 Gemini 调用核查结论

最后更新：2026-04-11

## 一、结论

当前**不能证明**项目2的页面设计任务曾“实际使用 Gemini 3.1 Pro 完成”。

更准确的说法是：
- 本地存在通过 Cursor bridge 发起到 Cursor Agent 的调用记录
- 这些记录的元数据里写了 `model = gemini3.1pro`
- 但本机当前 Cursor Agent 可用模型列表中**并没有 Gemini 3.1 Pro**
- 因此，之前所有“已实际调用 Gemini 3.1 Pro”的表述都不严谨，不能继续使用

## 二、已核查事实

### 1. 本地确有 Cursor bridge 记录

相关目录：
- `F:\codex\codex1\tools\cursor-bridge\runs\20260411-181257`
- `F:\codex\codex1\tools\cursor-bridge\runs\20260411-181502`

这些 run 中包含：
- `meta.json`
- `task.txt`
- `result.txt`

### 2. bridge 实际调用的是本机 Cursor Agent

`F:\codex\codex1\tools\cursor-bridge\invoke-cursor-agent.ps1` 的逻辑是：
- 优先找 Windows 的 `cursor-agent`
- 找不到则退回到 WSL 中的 `$HOME/.local/bin/agent`

而当前 run 的 `meta.json` 显示：
- `agent_kind = wsl`
- `agent_command = /home/ztk/.local/bin/agent`

### 3. 当前 WSL 中的 Cursor Agent 不支持 Gemini 3.1 Pro

实测：
- `agent --list-models`

返回可用模型只有：
- `auto`
- `composer-2-fast`
- `composer-2`
- `composer-1.5`
- `grok-4-20`
- `grok-4-20-thinking`
- `kimi-k2.5`

**Gemini 3.1 Pro 不在列表中。**

## 三、这意味着什么

这意味着：

1. `meta.json` 里写了 `model = gemini3.1pro`
   - 只能证明调用脚本曾尝试把这个字符串传给 Cursor Agent
   - **不能证明 Cursor Agent 真的接受并使用了 Gemini 3.1 Pro**

2. `result.txt` 有设计输出
   - 只能证明 Cursor Agent 返回了结果
   - **不能证明这个结果来自 Gemini 3.1 Pro**

3. 用户看到 Cursor 付费模型使用量没有增加
   - 与当前核查结果是一致的
   - 至少不能拿现有仓库证据反驳用户这个观察

## 四、需要纠正的说法

以后关于项目2设计稿来源，只能这样说：

- “通过 Cursor bridge / Cursor Agent 发起过设计任务”
- “当前无法核验具体使用的是 Gemini 3.1 Pro”

不能再说：

- “已确认调用 Gemini 3.1 Pro”
- “前后台设计已由 Gemini 3.1 Pro 完成”

## 五、怎么真正解决

### 方案A：先不再要求“必须 Gemini”

如果当前这台机器上的 Cursor Agent 不支持 Gemini 3.1 Pro，就不要再把“必须用 Gemini 3.1 Pro”写成硬要求。

改成：
- 允许使用当前 Cursor Agent 可选模型
- 但必须保留设计任务、结果文件和接入文档

### 方案B：如果你必须用 Gemini

那就需要先补齐**可核验链路**，满足以下任一条件：

1. 在 Cursor 中手动确认 Gemini 3.1 Pro 可选，并保留界面证据
2. 让 CLI 的 `agent --list-models` 实际出现 Gemini 3.1 Pro
3. 不通过 Cursor Agent，而是直接调用 Gemini 官方 API / 官方 SDK，并保存：
   - 调用脚本
   - 请求参数
   - 返回结果
   - 调用时间

在这三者做到之前，任何“Gemini 已实际使用”的说法都不应写进文档或汇报

## 六、立即执行的修正

本轮已做修正：
- 重写：
  - `docs/项目2-Gemini前台设计结果接入说明-v1.md`
  - `docs/项目2-Gemini后台设计结果接入说明-v1.md`
- 去掉“已核验实际调用 Gemini 3.1 Pro”的口径
- 新增本核查说明文档作为当前事实源
