export type RunMode = 'auto' | 'guided';
export type MockToggle = 'default' | 'real' | 'mock';

export interface WorkflowCapabilities {
  run_modes?: Record<string, { supported?: boolean; description?: string }>;
  export_formats?: Record<string, { supported?: boolean; aliases?: string[]; note?: string }>;
  platform_rules?: PlatformRule[];
}

export interface HealthPayload {
  status?: string;
  llm_model?: string;
  image_model?: string;
  vision_model?: string;
  llm_provider_route?: string;
  image_provider_route?: string;
  graph_version?: string;
  image_mock?: boolean;
  vision_review_mock?: boolean;
  checks?: {
    postgres_connectivity?: boolean | null;
  };
  llm_circuit_breaker?: {
    state?: string;
    failure_count?: number;
  };
}

export interface ResearchTopic {
  title: string;
  reason?: string;
  heat_score?: number;
  target_audience?: string;
  content_angle?: string;
}

export interface ImageAsset {
  status?: string;
  provider?: string;
  model?: string;
  asset_type?: string;
  usage?: string;
  web_path?: string;
  image_url?: string;
  requested_size?: string;
  latency_ms?: number;
  candidate_index?: number;
  is_primary?: boolean;
}

export interface VisualReview {
  theme_match_score?: number;
  readability_score?: number;
  composition_score?: number;
  overall_score?: number;
  passed?: boolean;
  risk_flags?: string[];
  feedback?: string;
  review_mode?: string;
  vision_model?: string;
}

export interface TextImageConsistency {
  status?: string;
  score?: number;
  matched_keywords?: string[];
  missing_keywords?: string[];
  note?: string;
}

export interface WorkflowResult {
  run_id?: string;
  request_id?: string;
  status?: string;
  title?: string;
  content?: string;
  tags?: string[];
  platform?: string;
  style?: string;
  brief?: string;
  export_formats?: string[];
  research_topics?: ResearchTopic[];
  image_asset?: ImageAsset;
  image_assets?: ImageAsset[];
  cover_candidates?: ImageAsset[];
  platform_rule?: PlatformRule;
  publish_package?: PublishPackage;
  review?: Record<string, unknown>;
  cover_visual_review?: VisualReview;
  text_image_consistency?: TextImageConsistency;
  trace?: string[];
  events?: Record<string, unknown>[];
  errors?: Record<string, unknown>[];
  node_metrics?: Record<string, unknown>[];
  metrics_summary?: Record<string, unknown>;
  content_package?: Record<string, unknown>;
  raw?: Record<string, unknown>;
}

export interface PlatformRule {
  platform?: string;
  label?: string;
  content_shape?: string;
  length_hint?: string;
  paragraph_hint?: string;
  tone_hint?: string;
  tag_count?: string;
  image_targets?: Record<string, number>;
  image_types?: string[];
  publish_checks?: string[];
  publish_steps?: string[];
}

export interface PublishPackage {
  platform?: string;
  title?: string;
  content?: string;
  tags?: string[];
  image_assets?: ImageAsset[];
  copy_blocks?: {
    title?: string;
    body?: string;
    tags?: string;
  };
  checks?: string[];
  manual_steps?: string[];
  automation_research?: Record<string, unknown>;
}

export interface WorkflowRequest {
  brief: string;
  platform: string;
  style: string;
  run_mode: RunMode;
  export_formats: string[];
  approval_decision: string;
  approval_note: string;
  reviewer_threshold: number;
  max_revisions: number;
  image_mock?: boolean;
  cover_candidate_count?: number;
  vision_review_mock?: boolean;
}

export interface ContinueRequest {
  run_id: string;
  selected_topic_index: number;
  approval_decision: string;
  approval_note: string;
  reviewer_threshold: number;
  max_revisions: number;
  export_formats: string[];
  image_mock?: boolean;
  cover_candidate_count?: number;
  vision_review_mock?: boolean;
}

export interface RewriteRequest {
  run_id: string;
  instruction: string;
  approval_decision: string;
  approval_note: string;
  reviewer_threshold?: number;
  max_revisions?: number;
  export_formats?: string[];
  image_mock?: boolean;
  cover_candidate_count?: number;
  vision_review_mock?: boolean;
}

export interface NodeRerunRequest {
  instruction: string;
  approval_decision: string;
  approval_note: string;
  reviewer_threshold?: number;
  max_revisions?: number;
  export_formats?: string[];
  image_mock?: boolean;
  cover_candidate_count?: number;
  vision_review_mock?: boolean;
}

export interface NodeDetail {
  node: string;
  index?: number;
  status?: string;
  phase?: string;
  latency_ms?: number;
  prompt_tokens?: number;
  completion_tokens?: number;
  total_tokens?: number;
  error?: string;
  input_summary?: string;
  output_summary?: string;
  events?: Record<string, unknown>[];
  raw_metric?: Record<string, unknown>;
}

export interface NodeDetailsPayload {
  run_id?: string;
  status?: string;
  nodes: NodeDetail[];
  metrics_summary?: Record<string, unknown>;
  errors?: Record<string, unknown>[];
}

export interface StreamCallbacks {
  onEvent?: (eventName: string, data: Record<string, unknown>) => void;
  onError?: (message: string) => void;
}

const JSON_HEADERS = {
  'Content-Type': 'application/json',
};

export const RUN_HISTORY_KEY = 'media-agent-frontend-history';

export interface RunHistoryEntry {
  run_id: string;
  request_id?: string;
  title?: string;
  status?: string;
  platform?: string;
  style?: string;
  created_at: string;
  image_count?: number;
  publish_ready?: boolean;
}

export interface RunListPayload {
  items: RunHistoryEntry[];
  count: number;
}

export interface AdminLogsPayload {
  items: Record<string, unknown>[];
  count: number;
}

export function loadRunHistory(): RunHistoryEntry[] {
  try {
    const raw = window.localStorage.getItem(RUN_HISTORY_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as RunHistoryEntry[];
    if (!Array.isArray(parsed)) return [];
    return parsed;
  } catch {
    return [];
  }
}

export function saveRunHistory(entry: RunHistoryEntry): void {
  const current = loadRunHistory();
  const next = [entry, ...current.filter((item) => item.run_id !== entry.run_id)].slice(0, 20);
  window.localStorage.setItem(RUN_HISTORY_KEY, JSON.stringify(next));
}

export async function getHealth(): Promise<HealthPayload> {
  return fetchJson<HealthPayload>('/health');
}

export async function getWorkflowCapabilities(): Promise<WorkflowCapabilities> {
  return fetchJson<WorkflowCapabilities>('/v2/workflow-capabilities');
}

export async function getPlatformRules(): Promise<{ platforms: PlatformRule[] }> {
  return fetchJson<{ platforms: PlatformRule[] }>('/v2/platform-rules');
}

export async function listRuns(limit = 20): Promise<RunListPayload> {
  return fetchJson<RunListPayload>(`/v2/runs?limit=${encodeURIComponent(String(limit))}`);
}

export async function getAdminLogs(limit = 80): Promise<AdminLogsPayload> {
  return fetchJson<AdminLogsPayload>(`/v2/admin/logs?limit=${encodeURIComponent(String(limit))}`);
}

export async function stopRun(runId: string): Promise<Record<string, unknown>> {
  return postJson<Record<string, unknown>>(`/v2/runs/${encodeURIComponent(runId)}/stop`, {});
}

export async function rewriteRun(payload: RewriteRequest): Promise<WorkflowResult> {
  const raw = await postJson<Record<string, unknown>>('/v2/run/rewrite', payload);
  return normalizeWorkflowResult(raw);
}

export async function getRunNodes(runId: string): Promise<NodeDetailsPayload> {
  return fetchJson<NodeDetailsPayload>(`/v2/runs/${encodeURIComponent(runId)}/nodes`);
}

export async function rerunNode(runId: string, node: string, payload: NodeRerunRequest): Promise<WorkflowResult> {
  const raw = await postJson<Record<string, unknown>>(
    `/v2/runs/${encodeURIComponent(runId)}/nodes/${encodeURIComponent(node)}/rerun`,
    payload,
  );
  return normalizeWorkflowResult(raw);
}

export async function updatePublishOverrides(
  runId: string,
  payload: { image_assets?: ImageAsset[]; cover_asset?: ImageAsset },
): Promise<WorkflowResult> {
  const response = await fetch(`/v2/runs/${encodeURIComponent(runId)}/publish-overrides`, {
    method: 'PATCH',
    headers: JSON_HEADERS,
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    const detail = await safeReadText(response);
    throw new Error(detail || `请求失败：${response.status}`);
  }
  return normalizeWorkflowResult((await response.json()) as Record<string, unknown>);
}

export async function runWorkflow(payload: WorkflowRequest): Promise<WorkflowResult> {
  const raw = await postJson<Record<string, unknown>>('/v2/run', payload);
  return normalizeWorkflowResult(raw);
}

export async function continueWorkflow(payload: ContinueRequest): Promise<WorkflowResult> {
  const raw = await postJson<Record<string, unknown>>('/v2/run/continue', payload);
  return normalizeWorkflowResult(raw);
}

export async function getRun(runId: string): Promise<WorkflowResult> {
  const raw = await fetchJson<Record<string, unknown>>(`/v2/runs/${encodeURIComponent(runId)}`);
  return normalizeWorkflowResult(raw);
}

export async function streamWorkflow(
  payload: WorkflowRequest,
  callbacks: StreamCallbacks = {},
  signal?: AbortSignal,
): Promise<WorkflowResult | null> {
  const response = await fetch('/v2/run/stream', {
    method: 'POST',
    headers: JSON_HEADERS,
    body: JSON.stringify(payload),
    signal,
  });

  if (!response.ok || !response.body) {
    const detail = await safeReadText(response);
    throw new Error(detail || `流式请求失败：${response.status}`);
  }

  const decoder = new TextDecoder('utf-8');
  const reader = response.body.getReader();
  let buffer = '';
  let finalResult: WorkflowResult | null = null;

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    let boundaryIndex = buffer.indexOf('\n\n');
    while (boundaryIndex !== -1) {
      const rawBlock = buffer.slice(0, boundaryIndex);
      buffer = buffer.slice(boundaryIndex + 2);
      const parsed = parseSseBlock(rawBlock);
      if (parsed) {
        callbacks.onEvent?.(parsed.event, parsed.data);
        if (parsed.event === 'error') {
          callbacks.onError?.(String(parsed.data.detail || '流式运行失败'));
        }
        if (parsed.event === 'final') {
          finalResult = normalizeWorkflowResult(parsed.data);
        }
      }
      boundaryIndex = buffer.indexOf('\n\n');
    }
  }

  return finalResult;
}

function parseSseBlock(block: string): { event: string; data: Record<string, unknown> } | null {
  const lines = block.split(/\r?\n/);
  let eventName = 'message';
  const dataLines: string[] = [];
  for (const line of lines) {
    if (line.startsWith('event:')) {
      eventName = line.slice(6).trim();
    } else if (line.startsWith('data:')) {
      dataLines.push(line.slice(5).trim());
    }
  }
  if (!dataLines.length) return null;
  try {
    return {
      event: eventName,
      data: JSON.parse(dataLines.join('\n')) as Record<string, unknown>,
    };
  } catch {
    return {
      event: eventName,
      data: { raw: dataLines.join('\n') },
    };
  }
}

function normalizeWorkflowResult(raw: Record<string, unknown>): WorkflowResult {
  const state = asRecord(raw.state) ?? raw;
  const draft = asRecord(state.draft) ?? asRecord(raw.draft) ?? {};
  const adapted = asRecord(state.adapted) ?? asRecord(raw.adapted) ?? {};
  const contentPackage = asRecord(state.content_package) ?? asRecord(raw.content_package) ?? {};
  const research = asRecord(state.research) ?? asRecord(raw.research) ?? {};
  const imageAsset = asRecord(state.image_asset) ?? asRecord(raw.image_asset) ?? {};
  const imageAssets =
    (state.image_assets as ImageAsset[] | undefined) ??
    (raw.image_assets as ImageAsset[] | undefined) ??
    (Array.isArray(contentPackage.image_assets_summary)
      ? (contentPackage.image_assets_summary as ImageAsset[])
      : []);
  const visualReview = asRecord(state.cover_visual_review) ?? asRecord(raw.cover_visual_review) ?? {};
  const consistency = asRecord(state.text_image_consistency) ?? asRecord(raw.text_image_consistency) ?? {};
  const metrics =
    asRecord(state.metrics_summary) ??
    asRecord(state.metrics) ??
    asRecord(raw.metrics_summary) ??
    asRecord(raw.metrics) ??
    {};
  const fullMetrics = asRecord(state.metrics) ?? asRecord(raw.metrics) ?? {};

  const publishPackage = asRecord(state.publish_package) ??
    asRecord(contentPackage.publish_package) ??
    asRecord(raw.publish_package) ??
    {};
  const publishCopyBlocks = asRecord(publishPackage.copy_blocks) ?? {};

  const title =
    asString(adapted.title) ||
    asString(publishCopyBlocks.title) ||
    asString(draft.title) ||
    asString(contentPackage.title) ||
    asString(state.title) ||
    asString(raw.title);

  const content =
    asString(adapted.content) ||
    asString(publishCopyBlocks.body) ||
    asString(draft.content) ||
    asString(contentPackage.content) ||
    asString(state.content) ||
    asString(raw.content);

  const tags =
    asStringArray(draft.tags) ??
    asStringArray(adapted.tags) ??
    asStringArray(contentPackage.tags) ??
    asStringArray(state.tags) ??
    asStringArray(raw.tags) ??
    [];

  const researchTopics = (research.topics as ResearchTopic[] | undefined) ?? [];
  const coverCandidates = (state.cover_candidates as ImageAsset[] | undefined) ??
    (raw.cover_candidates as ImageAsset[] | undefined) ??
    [];
  const trace = (state.trace as string[] | undefined) ?? (raw.trace as string[] | undefined) ?? [];
  const events = (state.events as Record<string, unknown>[] | undefined) ?? [];
  const errors = (state.errors as Record<string, unknown>[] | undefined) ?? [];
  const nodeMetrics =
    (fullMetrics.node_metrics as Record<string, unknown>[] | undefined) ??
    (metrics.node_metrics as Record<string, unknown>[] | undefined) ??
    [];

  return {
    run_id: asString(raw.run_id) || asString(state.run_id),
    request_id: asString(raw.request_id) || asString(state.request_id),
    status: asString(state.status) || asString(raw.status),
    title,
    content,
    tags,
    platform: asString(raw.platform) || asString(state.platform),
    style: asString(raw.style) || asString(state.style),
    brief: asString(raw.brief) || asString(state.brief),
    export_formats:
      asStringArray(raw.export_formats) ?? asStringArray(state.export_formats) ?? [],
    research_topics: researchTopics,
    image_asset: imageAsset as ImageAsset,
    image_assets: imageAssets.length ? imageAssets : (imageAsset ? [imageAsset as ImageAsset] : []),
    cover_candidates: coverCandidates,
    platform_rule: (asRecord(state.platform_rule) ?? asRecord(raw.platform_rule) ?? {}) as PlatformRule,
    publish_package: publishPackage as PublishPackage,
    review: (asRecord(state.review) ?? asRecord(raw.review) ?? {}) as Record<string, unknown>,
    cover_visual_review: visualReview as VisualReview,
    text_image_consistency: consistency as TextImageConsistency,
    trace,
    events,
    errors,
    node_metrics: nodeMetrics,
    metrics_summary: metrics,
    content_package: contentPackage,
    raw,
  };
}

async function fetchJson<T>(url: string): Promise<T> {
  const response = await fetch(url);
  if (!response.ok) {
    const detail = await safeReadText(response);
    throw new Error(detail || `请求失败：${response.status}`);
  }
  return (await response.json()) as T;
}

async function postJson<T>(url: string, body: unknown): Promise<T> {
  const response = await fetch(url, {
    method: 'POST',
    headers: JSON_HEADERS,
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    const detail = await safeReadText(response);
    throw new Error(detail || `请求失败：${response.status}`);
  }
  return (await response.json()) as T;
}

async function safeReadText(response: Response): Promise<string> {
  try {
    return await response.text();
  } catch {
    return '';
  }
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function asString(value: unknown): string {
  return typeof value === 'string' ? value : '';
}

function asStringArray(value: unknown): string[] | null {
  if (!Array.isArray(value)) return null;
  return value.filter((item): item is string => typeof item === 'string');
}
