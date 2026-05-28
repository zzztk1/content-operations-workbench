# 项目2-性能与TTFT开销调优记录（v1）
最后更新：2026-04-10

## 1. 这轮调优解决什么问题

上一轮我们已经把结构化输出稳定性拉高了，但也留下了一个真实问题：

- `direct_rate` 很高
- 但平均延迟、`TTFT` 和 total token 也偏高

这轮调优的目标就是三件事：

1. 降低平均延迟
2. 降低 `TTFT`（Time To First Token，首字延迟）
3. 降低单位请求的推理资源开销

这里的“开销”当前主要用 token 消耗来表达，不直接写美元成本，因为项目2当前走的是阶跃星辰 `Step Plan`，不是标准按 token 计费口径。

## 2. 方法路线

### 2.1 先保住结构化稳定性

这轮的第一原则不是盲目追求更快，而是先保住上一轮最值钱的成果：

- 三个关键结构化节点保持 `direct`
- `fallback_rate` 不允许变差

### 2.2 只做 prompt 和上下文瘦身

这轮不改主图、不改状态、不改数据库，只做低风险瘦身：

- `research_topic`
  - 候选选题从 3 个压到 2 个
  - 字段长度进一步收紧
- `write_draft`
  - `style_hints` 从更长提示压成更短版本
  - 正文从 3 段短段落压成 2 段短段落
  - 目标长度从 `180-240` 汉字压到 `140-180`
  - prompt 字段精简
- `review_structured`
  - review 输入正文截断从 `1400` 压到 `900`
  - feedback 目标从 `<= 28` 字压到 `<= 18` 字
  - repair 上限同步压缩

### 2.3 补一轮同路线模型 A/B

除了 prompt 瘦身，我还做了同一 `Step Plan` 路线下的模型 A/B：

- `step-3.5-flash`
- `step-3.5-flash-2603`

目的很简单：

- 判断是“继续改 prompt”更划算
- 还是“直接换同路线模型”更划算

## 3. 代码改动点

核心改动文件：

- [engine.py](F:/codex/codex1/projects/media-agent/src/langgraph_v2/engine.py)

具体改动：

- `_compress_style_features`
  - 默认保留 2 条，不再保留 3 条
  - 文本上限从 120 压到 70
- `node_research_topic`
  - 选题数从 3 改成 2
  - title / reason / target_audience / content_angle 长度收紧
- `node_write_draft`
  - 精简 prompt 字段
  - 正文长度压缩
  - 从 3 段改成 2 段
  - repair 上限从 700 压到 360
- `node_review_structured`
  - review 输入正文截断从 1400 压到 900
  - feedback 更短
  - repair 上限从 220 压到 160

## 4. 评测设计

### 4.1 before 基线

- [latest_step_plan_perf_before.json](F:/codex/codex1/projects/media-agent/benchmarks/latest_step_plan_perf_before.json)
- 标签：`structured_stability_v8_before_perf`

### 4.2 after 结果

- [latest_step_plan_perf_after.json](F:/codex/codex1/projects/media-agent/benchmarks/latest_step_plan_perf_after.json)
- 标签：`perf_tuned_prompt_v1`

### 4.3 before / after 对比

- [latest_step_plan_perf_compare.json](F:/codex/codex1/projects/media-agent/benchmarks/latest_step_plan_perf_compare.json)

### 4.4 模型 A/B

- [latest_step_plan_perf_after_2603.json](F:/codex/codex1/projects/media-agent/benchmarks/latest_step_plan_perf_after_2603.json)
- [latest_step_plan_model_ab_compare.json](F:/codex/codex1/projects/media-agent/benchmarks/latest_step_plan_model_ab_compare.json)

## 5. 这轮结果

### 5.1 结构化稳定性

before：

- `direct_rate = 100%`
- `salvage_rate = 0%`
- `fallback_rate = 0%`

after：

- `direct_rate = 100%`
- `salvage_rate = 0%`
- `fallback_rate = 0%`

结论：

- 性能优化没有破坏结构化稳定性

### 5.2 性能与资源开销

来自 [latest_step_plan_perf_compare.json](F:/codex/codex1/projects/media-agent/benchmarks/latest_step_plan_perf_compare.json)：

- 平均延迟
  - `58561.63 ms -> 40522.05 ms`
  - `-18039.58 ms`
  - `-30.8%`
- 平均 prompt token
  - `797 -> 701`
  - `-96`
  - `-12.05%`
- 平均 completion token
  - `8800 -> 5780.67`
  - `-3019.33`
  - `-34.31%`
- 平均 total token
  - `9597 -> 6481.67`
  - `-3115.33`
  - `-32.46%`
- 平均 `TTFT`
  - `33584.9 ms -> 9062.58 ms`
  - `-24522.32 ms`
  - `-73.02%`

结论：

- 这轮不是“只快一点”
- 而是在保持 `100% direct` 的前提下，真正把延迟、`TTFT` 和 token 开销都压下来了

## 6. 模型 A/B 结果

来自 [latest_step_plan_model_ab_compare.json](F:/codex/codex1/projects/media-agent/benchmarks/latest_step_plan_model_ab_compare.json)：

对比：

- before：`step-3.5-flash`
- after：`step-3.5-flash-2603`

结果：

- 平均延迟
  - 再降 `1137.46 ms`
- 平均 total token
  - 再降 `33`
- 但平均 `TTFT`
  - 上升 `6348.62 ms`

结论：

- `2603` 在整体延迟上略好
- 但在 `TTFT` 上明显更差

因此本轮保留的默认主线仍然是：

- `step-3.5-flash`

原因：

- 项目2当前更重视流式首字体验

## 7. 主链路复验

最新真实 smoke：

- [latest_step_plan_runtime_report.json](F:/codex/codex1/projects/media-agent/benchmarks/latest_step_plan_runtime_report.json)

当前主链路状态：

- `all_passed = true`
- `research_topic = direct`
- `write_draft = direct`
- `review_structured = repair:direct`

这说明：

- 默认主线仍然稳定可跑
- 没有因为性能优化把系统跑坏

## 8. 当前最适合写进简历的内容

可以安全写：

- 通过 prompt 与上下文瘦身，在保持关键结构化节点稳定直出的前提下，降低平均延迟、`TTFT` 和单位请求 token 开销
- 基于真实 before / after 报告完成性能调优，而不是只靠主观感觉

当前可以量化写的结果：

- 平均延迟降低 `30.8%`
- 平均 `TTFT` 降低 `73.02%`
- 平均 total token 降低 `32.46%`

注意：

- 这些数字只对应当前 3 场景 benchmark
- 不能泛化成所有场景或生产环境收益

## 9. 这轮最终结论

这轮调优的价值在于：

- 它不是牺牲结构化稳定性换来的性能
- 而是在保持 `100% direct` 的前提下，真正把延迟、`TTFT` 和 token 开销压了下来

当前最准确的说法是：

> 项目2在完成结构化稳定性调优后，又做了一轮性能与资源开销优化；最终在当前 3 场景真实 benchmark 中，保持关键结构化节点 `100% direct` 不变的同时，将平均延迟降低 `30.8%`、平均 `TTFT` 降低 `73.02%`、平均 total token 降低 `32.46%`。
