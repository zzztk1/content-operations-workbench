# Low-risk optimization pass (image + text tokens)

Date: 2026-04-11

## What changed (code)

| Area | Change |
|------|--------|
| Image download | Replaced `urlretrieve` with `Request` + `urlopen(..., timeout=IMAGE_DOWNLOAD_TIMEOUT_SEC)` and single `write_bytes`, so remote hangs cannot block indefinitely and work matches configured timeout. |
| Image batch | Concurrent cover generation uses a `ThreadPoolExecutor(max_workers=limit)` aligned with the semaphore limit, instead of the process-default executor pool—reduces unnecessary thread churn for small batches. |
| Image dirs | Cache `outputs/images` path after first `mkdir` to avoid repeated filesystem work across batch items. |
| Repair path | JSON repair prompt truncates `invalid_output` at **1800** chars (was 2800) to cut repair-call tokens when repair triggers. |
| Write / review | Slimmer system prompts for `write_draft` and `review_structured`: removed duplicated length/tone/hook lines that already appear in the user block; shorter review instructions. |
| Batch compare script | Clarifies metrics: `sum_per_item_wall_time_ms`, `batch_wall_clock_ms`, `compare_notes`, `benchmark_settings`; default `IMAGE_BATCH_COMPARE_CONCURRENCY` **3** to match historical runs (set to `2` to experiment with capped fan-out). |

## Benchmark files (regenerate locally)

Automated benchmark execution was not available in this environment; run on your machine with a valid `.env` (StepFun API keys, real image calls as needed).

**Text / token compare (step plan streaming):**

```bash
cd /path/to/media-agent
python3 benchmarks/evaluate_step_plan_tuning.py \
  --label perf_token_slim_v2 \
  --output benchmarks/latest_step_plan_perf_after_token_slim_v2.json
python3 benchmarks/compare_step_plan_tuning.py \
  --before benchmarks/latest_step_plan_perf_after.json \
  --after benchmarks/latest_step_plan_perf_after_token_slim_v2.json \
  --output benchmarks/latest_step_plan_perf_compare.json
```

Use `latest_step_plan_perf_after.json` (label `perf_tuned_prompt_v1`) as the “before” snapshot so the compare isolates this pass from older tuning.

**Image batch compare (real API, long-running):**

```bash
IMAGE_BENCHMARK_REAL=true python3 benchmarks/compare_image_batch_modes.py
```

Writes `benchmarks/latest_image_batch_compare_report.json`.

## Key numbers already on disk (before this pass)

These are **not** after this code change; they are the last committed reports for context.

### Image (`benchmarks/latest_image_batch_compare_report.json`, 2026-04-11)

- `sequential.total_elapsed_ms`: **248019.19**
- `concurrent.total_elapsed_ms`: **207288.21**
- `comparison.elapsed_reduction_pct`: **16.42**
- `concurrent.concurrency`: **3** (historical run)

### Text (`benchmarks/latest_step_plan_perf_compare.json`, 2026-04-10)

Compares older baseline → `perf_tuned_prompt_v1`:

- `avg_total_tokens`: before **9597**, after **6481.67** (delta **-3115.33**)
- `structured_compare.direct_rate`: **1.0** → **1.0**

### Text (`benchmarks/latest_step_plan_perf_after.json` summary)

- `avg_total_tokens`: **6481.67**
- `structured_output.direct_rate`: **1.0**

After you run the commands above, fill in **new** `avg_*_tokens` and `direct_rate` from the regenerated JSON files.

## Resume / evidence wording (point 4 & 5)

**Point 4 (image throughput / batch behavior)**  
- **Safe after re-run:** Cite `latest_image_batch_compare_report.json` with `generated_at`, `image_model`, `sequential` vs `concurrent` `total_elapsed_ms`, and `benchmark_settings.batch_concurrency` if present.  
- **Still cannot claim without a fresh report:** A specific “after optimization” wall-time delta for this pass; USD cost unless you have a truthful price model (StepFun is already marked subscription-not-token-billed in metrics).

**Point 5 (tokens / inference cost)**  
- **Safe after re-run:** Report **prompt / completion / total** token averages from `evaluate_step_plan_tuning` + `compare_step_plan_tuning`; note `direct_rate` from structured summary.  
- **Still cannot claim:** Exact dollar savings on StepFun; use token metrics only unless `estimated_cost_available` is true.

### Status vs “done with measured evidence”

| Item | Status |
|------|--------|
| Point 4 | **Done but claim must be softened** until `compare_image_batch_modes.py` is re-run and `latest_image_batch_compare_report.json` is updated on this revision. Implementation + benchmark methodology improvements are in place. |
| Point 5 | **Done but claim must be softened** until `evaluate_step_plan_tuning.py` + `compare_step_plan_tuning.py` produce new JSON with this prompt slimming; token direction is plausible but not measured here. |

If both benchmark commands succeed and `direct_rate` stays **1.0**, you can upgrade to **“done with measured evidence”** for token deltas and image batch wall-clock (subject to run-to-run variance on the image API).
