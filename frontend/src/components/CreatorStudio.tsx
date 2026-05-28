import { useEffect, useRef, useState } from 'react';
import { Clipboard, Loader2, PackageCheck, Play, Square, Waves } from 'lucide-react';
import {
  continueWorkflow,
  getHealth,
  getPlatformRules,
  getRun,
  getRunNodes,
  getWorkflowCapabilities,
  listRuns,
  loadRunHistory,
  rerunNode,
  rewriteRun,
  saveRunHistory,
  streamWorkflow,
  runWorkflow,
  stopRun,
  updatePublishOverrides,
  type HealthPayload,
  type MockToggle,
  type NodeDetail,
  type PlatformRule,
  type ResearchTopic,
  type RunHistoryEntry,
  type RunMode,
  type WorkflowCapabilities,
  type WorkflowRequest,
  type WorkflowResult,
} from '../lib/mediaAgentApi';

const DEFAULT_BRIEF =
  '写一篇公众号文章，主题是“信息越来越多，为什么真正有判断力的人反而更少了”。要求带一点趋势观察和个人思考，适合公众号深度表达。';

type CreatorView = 'creator' | 'monitor' | 'topics' | 'editor' | 'assets' | 'publish' | 'history';

export default function CreatorStudio({ view }: { view: CreatorView }) {
  const [brief, setBrief] = useState(DEFAULT_BRIEF);
  const [platform, setPlatform] = useState('公众号');
  const [style, setStyle] = useState('经验总结');
  const [runMode, setRunMode] = useState<RunMode>('auto');
  const [reviewerThreshold, setReviewerThreshold] = useState(21);
  const [maxRevisions, setMaxRevisions] = useState(1);
  const [approvalDecision, setApprovalDecision] = useState('approve');
  const [approvalNote, setApprovalNote] = useState('frontend-demo');
  const [imageMode, setImageMode] = useState<MockToggle>('default');
  const [visionMode, setVisionMode] = useState<MockToggle>('default');
  const [coverCandidateCount, setCoverCandidateCount] = useState(3);
  const [exportFormats, setExportFormats] = useState<string[]>(['json', 'md']);

  const [health, setHealth] = useState<HealthPayload | null>(null);
  const [capabilities, setCapabilities] = useState<WorkflowCapabilities | null>(null);
  const [result, setResult] = useState<WorkflowResult | null>(null);
  const [logs, setLogs] = useState<string[]>([]);
  const [isRunning, setIsRunning] = useState(false);
  const [error, setError] = useState('');
  const [runId, setRunId] = useState('');
  const [requestId, setRequestId] = useState('');
  const [guidedTopics, setGuidedTopics] = useState<ResearchTopic[]>([]);
  const [selectedTopicIndex, setSelectedTopicIndex] = useState<number | null>(null);
  const [ttftMs, setTtftMs] = useState<number | null>(null);
  const [selectedCoverIndex, setSelectedCoverIndex] = useState(0);
  const [selectedAssetIndex, setSelectedAssetIndex] = useState(0);
  const [replacementImageUrl, setReplacementImageUrl] = useState('');
  const [coverReplacementUrl, setCoverReplacementUrl] = useState('');
  const [assetOverrides, setAssetOverrides] = useState<Record<number, string>>({});
  const [rewriteInstruction, setRewriteInstruction] = useState('');
  const [platformRules, setPlatformRules] = useState<PlatformRule[]>([]);
  const [historyRuns, setHistoryRuns] = useState<RunHistoryEntry[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [nodeDetails, setNodeDetails] = useState<NodeDetail[]>([]);
  const [selectedNode, setSelectedNode] = useState('');
  const [nodeRerunInstruction, setNodeRerunInstruction] = useState('');
  const streamAbortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    void refreshStatus();
  }, []);

  useEffect(() => {
    if (view !== 'history') return;
    void refreshHistory();
  }, [view]);

  useEffect(() => {
    if (view !== 'publish') return;
    void getPlatformRules()
      .then((payload) => setPlatformRules(payload.platforms ?? []))
      .catch((e) => setError(messageOf(e, '平台规则加载失败')));
  }, [view]);

  useEffect(() => {
    if (view !== 'monitor' || !runId) return;
    void refreshNodeDetails();
  }, [view, runId]);

  useEffect(() => {
    setReplacementImageUrl(assetOverrides[selectedAssetIndex] ?? '');
  }, [assetOverrides, selectedAssetIndex]);

  async function refreshStatus() {
    try {
      const [healthPayload, capabilityPayload] = await Promise.all([getHealth(), getWorkflowCapabilities()]);
      setHealth(healthPayload);
      setCapabilities(capabilityPayload);
      if (capabilityPayload.platform_rules?.length) {
        setPlatformRules(capabilityPayload.platform_rules);
      }
    } catch (e) {
      setError(messageOf(e, '系统状态刷新失败'));
    }
  }

  function payload(): WorkflowRequest {
    return {
      brief,
      platform,
      style,
      run_mode: runMode,
      export_formats: exportFormats,
      approval_decision: approvalDecision,
      approval_note: approvalNote,
      reviewer_threshold: reviewerThreshold,
      max_revisions: maxRevisions,
      image_mock: mapToggle(imageMode),
      cover_candidate_count: coverCandidateCount,
      vision_review_mock: mapToggle(visionMode),
    };
  }

  function resetBeforeRun() {
    setError('');
    setResult(null);
    setLogs([]);
    setGuidedTopics([]);
    setSelectedTopicIndex(null);
    setTtftMs(null);
    setSelectedCoverIndex(0);
    setSelectedAssetIndex(0);
    setReplacementImageUrl('');
    setCoverReplacementUrl('');
    setAssetOverrides({});
  }

  function commit(next: WorkflowResult) {
    setResult(next);
    setRunId(next.run_id ?? '');
    setRequestId(next.request_id ?? '');
    const topics = next.research_topics ?? [];
    setGuidedTopics(next.status === 'awaiting_topic_selection' ? topics : []);
    if (next.run_id) {
      saveRunHistory({
        run_id: next.run_id,
        request_id: next.request_id,
        title: next.title || '(无标题)',
        status: next.status,
        platform: next.platform,
        style: next.style,
        created_at: new Date().toISOString(),
        image_count: next.image_assets?.length ?? 0,
        publish_ready: Boolean(next.publish_package),
      });
    }
  }

  async function onStreamRun() {
    if (!brief.trim()) return setError('请先输入创作需求。');
    resetBeforeRun();
    setIsRunning(true);
    const controller = new AbortController();
    streamAbortRef.current = controller;
    try {
      const startTs = Date.now();
      let firstTokenCaptured = false;
      const finalResult = await streamWorkflow(payload(), {
        onEvent: (eventName, data) => {
          if (eventName === 'start') {
            setRunId(asString(data.run_id));
            setRequestId(asString(data.request_id));
          }
          if (eventName === 'token' && !firstTokenCaptured) {
            firstTokenCaptured = true;
            setTtftMs(Date.now() - startTs);
          }
          if (eventName === 'update') {
            const node = asString(data.node) || asString(data.phase) || eventName;
            setLogs((prev) => [`${labelOf(node)}：${asString(data.status) || '已更新'}`, ...prev].slice(0, 20));
          }
          if (eventName === 'error') {
            setError(asString(data.detail) || '流式运行失败');
          }
        },
      }, controller.signal);
      if (finalResult) commit(finalResult);
    } catch (e) {
      if (e instanceof DOMException && e.name === 'AbortError') {
        setLogs((prev) => ['流式请求已在前端中止', ...prev].slice(0, 20));
        return;
      }
      setError(messageOf(e, '流式运行失败'));
    } finally {
      setIsRunning(false);
      streamAbortRef.current = null;
    }
  }

  async function onSyncRun() {
    if (!brief.trim()) return setError('请先输入创作需求。');
    resetBeforeRun();
    setIsRunning(true);
    try {
      commit(await runWorkflow(payload()));
    } catch (e) {
      setError(messageOf(e, '同步运行失败'));
    } finally {
      setIsRunning(false);
    }
  }

  async function onContinue() {
    if (!runId || selectedTopicIndex === null) return setError('请先选择一个候选选题。');
    setIsRunning(true);
    try {
      commit(
        await continueWorkflow({
          run_id: runId,
          selected_topic_index: selectedTopicIndex,
          approval_decision: approvalDecision,
          approval_note: approvalNote,
          reviewer_threshold: reviewerThreshold,
          max_revisions: maxRevisions,
          export_formats: exportFormats,
          image_mock: mapToggle(imageMode),
          cover_candidate_count: coverCandidateCount,
          vision_review_mock: mapToggle(visionMode),
        }),
      );
    } catch (e) {
      setError(messageOf(e, '继续执行失败'));
    } finally {
      setIsRunning(false);
    }
  }

  async function onRefreshRun() {
    if (!runId) return setError('当前还没有 Run ID。');
    try {
      commit(await getRun(runId));
    } catch (e) {
      setError(messageOf(e, '回查失败'));
    }
  }

  async function onStopRun() {
    if (!runId) return setError('当前还没有可停止的 Run ID。');
    try {
      streamAbortRef.current?.abort();
      await stopRun(runId);
      setLogs((prev) => [`已请求停止：${runId}`, ...prev].slice(0, 20));
      setIsRunning(false);
    } catch (e) {
      setError(messageOf(e, '停止请求失败'));
    }
  }

  async function refreshHistory() {
    setHistoryLoading(true);
    try {
      const runList = await listRuns(30);
      setHistoryRuns(runList.items.length ? runList.items : loadRunHistory());
      setError('');
    } catch (e) {
      setHistoryRuns(loadRunHistory());
      setError(messageOf(e, '历史记录加载失败，已回退到本地缓存。'));
    } finally {
      setHistoryLoading(false);
    }
  }

  async function onLoadHistoryRun(targetRunId: string) {
    setIsRunning(true);
    try {
      commit(await getRun(targetRunId));
      setError('');
    } catch (e) {
      setError(messageOf(e, '历史运行回查失败'));
    } finally {
      setIsRunning(false);
    }
  }

  async function onRewrite() {
    if (!runId) return setError('当前还没有 Run ID，无法重写。');
    if (!rewriteInstruction.trim()) return setError('请先输入重写指令。');
    setIsRunning(true);
    try {
      commit(
        await rewriteRun({
          run_id: runId,
          instruction: rewriteInstruction.trim(),
          approval_decision: approvalDecision,
          approval_note: approvalNote,
          reviewer_threshold: reviewerThreshold,
          max_revisions: maxRevisions,
          export_formats: exportFormats,
          image_mock: mapToggle(imageMode),
          cover_candidate_count: coverCandidateCount,
          vision_review_mock: mapToggle(visionMode),
        }),
      );
    } catch (e) {
      setError(messageOf(e, '重写失败'));
    } finally {
      setIsRunning(false);
    }
  }

  async function refreshNodeDetails() {
    if (!runId) return;
    try {
      const payload = await getRunNodes(runId);
      const nodes = payload.nodes ?? [];
      setNodeDetails(nodes);
      if (!selectedNode && nodes.length) setSelectedNode(nodes[0].node);
    } catch (e) {
      setError(messageOf(e, '节点详情加载失败'));
    }
  }

  async function onRerunSelectedNode() {
    if (!runId || !selectedNode) return setError('请先选择一个节点。');
    setIsRunning(true);
    try {
      commit(
        await rerunNode(runId, selectedNode, {
          instruction: nodeRerunInstruction.trim(),
          approval_decision: approvalDecision,
          approval_note: approvalNote || 'node-rerun',
          reviewer_threshold: reviewerThreshold,
          max_revisions: maxRevisions,
          export_formats: exportFormats,
          image_mock: mapToggle(imageMode),
          cover_candidate_count: coverCandidateCount,
          vision_review_mock: mapToggle(visionMode),
        }),
      );
      setNodeRerunInstruction('');
    } catch (e) {
      setError(messageOf(e, '节点重跑失败'));
    } finally {
      setIsRunning(false);
    }
  }

  async function copyText(text: string, label: string) {
    try {
      await navigator.clipboard.writeText(text);
      setLogs((prev) => [`已复制：${label}`, ...prev].slice(0, 20));
    } catch {
      setError(`复制失败：${label}`);
    }
  }

  async function persistPublishOverrides(nextAssets: typeof publishImageAssets, nextCover?: typeof mainCover) {
    if (!runId) return;
    try {
      commit(await updatePublishOverrides(runId, {
        image_assets: nextAssets,
        cover_asset: nextCover || nextAssets[0],
      }));
    } catch (e) {
      setError(messageOf(e, '发布图片覆盖保存失败'));
    }
  }

  async function applyCoverReplacement() {
    if (!mainCover) return setError('当前还没有可保存的封面。');
    const coverAsset = {
      ...mainCover,
      web_path: coverReplacementUrl.trim() || mainCover.web_path,
      image_url: coverReplacementUrl.trim() || mainCover.image_url,
    };
    const nextAssets = publishImageAssets.length
      ? publishImageAssets.map((asset, index) => (index === 0 ? { ...asset, ...coverAsset } : asset))
      : [coverAsset];
    await persistPublishOverrides(nextAssets, coverAsset);
    setLogs((prev) => ['已保存封面到发布清单', ...prev].slice(0, 20));
  }

  async function applyAssetReplacement() {
    const nextUrl = replacementImageUrl.trim();
    if (!selectedAsset) return setError('请先选择一个图片素材。');
    const nextOverrides = { ...assetOverrides };
    if (nextUrl) {
      nextOverrides[selectedAssetIndex] = nextUrl;
    } else {
      delete nextOverrides[selectedAssetIndex];
    }
    const nextEffectiveAssets = imageAssets.map((asset, index) => {
      const overrideUrl = nextOverrides[index]?.trim();
      return overrideUrl
        ? {
            ...asset,
            web_path: overrideUrl,
            image_url: overrideUrl,
            status: `${asset.status || 'ready'} / manually_replaced`,
          }
        : asset;
    });
    const nextPublishAssets = nextEffectiveAssets.map((asset, index) => (index === 0 && mainCover ? { ...asset, ...mainCover } : asset));
    setAssetOverrides((prev) => {
      const next = { ...prev };
      if (nextUrl) {
        next[selectedAssetIndex] = nextUrl;
      } else {
        delete next[selectedAssetIndex];
      }
      return next;
    });
    await persistPublishOverrides(nextPublishAssets);
    setLogs((prev) => [`已更新发布图片清单：${selectedAsset.usage || `素材 ${selectedAssetIndex + 1}`}`, ...prev].slice(0, 20));
  }

  function resetAssetReplacement() {
    setAssetOverrides((prev) => {
      const next = { ...prev };
      delete next[selectedAssetIndex];
      return next;
    });
    setReplacementImageUrl('');
  }

  const covers = result?.cover_candidates ?? [];
  const imageAssets = result?.image_assets?.length
    ? result.image_assets
    : result?.image_asset
      ? [result.image_asset]
      : [];
  const selectedAsset = imageAssets[selectedAssetIndex] ?? imageAssets[0];
  const effectiveImageAssets = imageAssets.map((asset, index) => {
    const overrideUrl = assetOverrides[index]?.trim();
    return overrideUrl
      ? {
          ...asset,
          web_path: overrideUrl,
          image_url: overrideUrl,
          status: `${asset.status || 'ready'} / manually_replaced`,
        }
      : asset;
  });
  const selectedAssetEffective = effectiveImageAssets[selectedAssetIndex] ?? effectiveImageAssets[0];
  const selectedAssetUrl = selectedAssetEffective?.web_path || selectedAssetEffective?.image_url || '';
  const selectedCoverBase = covers[selectedCoverIndex] ?? result?.image_asset;
  const mainCover = coverReplacementUrl.trim()
    ? {
        ...(selectedCoverBase ?? {}),
        web_path: coverReplacementUrl.trim(),
        image_url: coverReplacementUrl.trim(),
        status: `${selectedCoverBase?.status || 'ready'} / manually_replaced`,
      }
    : selectedCoverBase;
  const body = result?.content?.trim() || '当前还没有可展示的正文。';
  const publishPackage = result?.publish_package;
  const publishImageAssets = effectiveImageAssets.map((asset, index) => {
    if (index === 0 && mainCover) {
      return { ...asset, ...mainCover, usage: asset.usage || mainCover.usage || '封面图' };
    }
    return asset;
  });
  const selectedNodeDetail = nodeDetails.find((item) => item.node === selectedNode) ?? nodeDetails[0];
  const review = result?.review ?? {};
  const reviewTotal = numberOf(review.total_score);
  const reviewPassed = typeof review.passed === 'boolean' ? review.passed : reviewTotal !== null ? reviewTotal >= reviewerThreshold : null;
  const platformOptions = (platformRules.length ? platformRules : capabilities?.platform_rules ?? [])
    .map((rule) => rule.platform || rule.label || '')
    .filter(Boolean);
  const platformRule =
    result?.platform_rule ??
    platformRules.find((rule) => rule.platform === platform || rule.label === platform);
  const viewTitle: Record<CreatorView, string> = {
    creator: '创作工作台',
    monitor: '流程监控',
    topics: '选题决策',
    editor: '内容编辑',
    assets: '图片素材',
    publish: '发布准备',
    history: '历史回查',
  };

  const layoutClass =
    view === 'creator'
      ? 'grid gap-4 lg:grid-cols-[340px_minmax(0,1fr)]'
      : view === 'history'
        ? 'grid gap-4 lg:grid-cols-[320px_minmax(0,1fr)]'
        : 'grid gap-4';

  return (
    <div aria-label={viewTitle[view]} className={layoutClass}>
      {error ? (
        <div className={view === 'creator' || view === 'history' ? 'lg:col-span-2' : ''}>
          <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div>
        </div>
      ) : null}

      {view === 'creator' ? (
      <section className="rounded-xl border border-slate-200/80 bg-white p-5 shadow-[0_1px_2px_rgba(15,23,42,0.04)]">
        <div className="mb-4 flex items-center justify-between">
          <div>
            <h2 className="text-lg font-semibold">任务配置</h2>
            <p className="text-sm text-slate-500">直接对接真实后端接口。</p>
          </div>
          <button type="button" onClick={() => void refreshStatus()} className="rounded-xl bg-slate-100 hover:bg-slate-200 px-3 py-2 text-sm">
            刷新状态
          </button>
        </div>
        <div className="space-y-3">
          <label className="block">
            <span className="mb-2 block text-sm font-medium">Brief</span>
            <textarea value={brief} onChange={(e) => setBrief(e.target.value)} rows={7} className="w-full rounded-lg border border-slate-200 bg-white px-4 py-3 text-sm leading-6 outline-none focus:border-teal-700 focus:ring-2 focus:ring-teal-700/10" />
          </label>
          <div className="grid gap-3 sm:grid-cols-2">
            <Select label="平台" value={platform} onChange={setPlatform} options={platformOptions.length ? platformOptions : ['公众号', '小红书', '知乎']} />
            <Select label="风格" value={style} onChange={setStyle} options={['经验总结', '趋势观察', '种草推荐', '理性分析']} />
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <Select label="运行模式" value={runMode} onChange={(v) => setRunMode(v as RunMode)} options={['auto', 'guided']} labels={{ auto: '一键自动生成', guided: '步步引导生成' }} />
            <Select label="封面配图" value={imageMode} onChange={(v) => setImageMode(v as MockToggle)} options={['default', 'real', 'mock']} labels={{ default: '跟随服务默认', real: '真实配图', mock: 'Mock 配图' }} />
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <Select label="视觉质检" value={visionMode} onChange={(v) => setVisionMode(v as MockToggle)} options={['default', 'real', 'mock']} labels={{ default: '跟随服务默认', real: '真实视觉模型', mock: 'Mock 视觉质检' }} />
            <Select label="封面候选数" value={String(coverCandidateCount)} onChange={(v) => setCoverCandidateCount(Number(v))} options={['1', '2', '3', '4']} labels={{ '1': '1 张', '2': '2 张', '3': '3 张', '4': '4 张' }} />
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <NumberField label="审核分数线" value={reviewerThreshold} onChange={setReviewerThreshold} min={1} max={30} />
            <NumberField label="最大重写轮数" value={maxRevisions} onChange={setMaxRevisions} min={0} max={5} />
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <Select label="审批结论" value={approvalDecision} onChange={setApprovalDecision} options={['approve', 'needs_edit', 'reject']} labels={{ approve: '通过', needs_edit: '需修改', reject: '拒绝' }} />
            <label className="block">
              <span className="mb-2 block text-sm font-medium">审批备注</span>
              <input value={approvalNote} onChange={(e) => setApprovalNote(e.target.value)} className="w-full rounded-lg border border-slate-200 bg-white px-4 py-3 text-sm outline-none focus:border-teal-700 focus:ring-2 focus:ring-teal-700/10" />
            </label>
          </div>
          <div>
            <span className="mb-2 block text-sm font-medium">导出格式</span>
            <div className="flex flex-wrap gap-2">
              {['json', 'md', 'txt', 'html'].map((format) => (
                <label key={format} className={`rounded-full border px-3 py-2 text-sm ${exportFormats.includes(format) ? 'border-amber-700 bg-amber-50 text-amber-700' : 'border-slate-200 bg-slate-50 text-slate-600'}`}>
                  <input type="checkbox" className="mr-2" checked={exportFormats.includes(format)} onChange={() => setExportFormats(toggleFormat(exportFormats, format))} />
                  {format.toUpperCase()}
                </label>
              ))}
            </div>
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <button type="button" onClick={() => void onStreamRun()} disabled={isRunning} className="flex items-center justify-center gap-2 rounded-lg bg-teal-700 hover:bg-teal-800 px-4 py-3 font-medium text-white disabled:opacity-60">{isRunning ? <Loader2 size={18} className="animate-spin" /> : <Waves size={18} />}开始流式运行</button>
            <button type="button" onClick={() => void onSyncRun()} disabled={isRunning} className="flex items-center justify-center gap-2 rounded-lg bg-slate-100 hover:bg-slate-200 px-4 py-3 font-medium text-slate-800 disabled:opacity-60">{isRunning ? <Loader2 size={18} className="animate-spin" /> : <Play size={18} />}同步运行</button>
          </div>
          <div className="grid gap-3 sm:grid-cols-3">
            <button type="button" onClick={() => void onContinue()} disabled={selectedTopicIndex === null || !guidedTopics.length || isRunning} className="rounded-lg border border-slate-200 bg-white px-4 py-3 text-sm font-medium disabled:opacity-50">选题后继续</button>
            <button type="button" onClick={() => void onRefreshRun()} disabled={!runId || isRunning} className="rounded-lg border border-slate-200 bg-white px-4 py-3 text-sm font-medium disabled:opacity-50">刷新状态</button>
            <button type="button" onClick={() => void onStopRun()} disabled={!runId} className="flex items-center justify-center gap-2 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm font-medium text-red-700 hover:bg-red-100 disabled:opacity-50"><Square size={14} />停止</button>
          </div>
        </div>
      </section>
      ) : null}

      {view !== 'creator' && view !== 'history' ? (
        <section className="rounded-xl border border-slate-200/80 bg-white px-5 py-4 shadow-[0_1px_2px_rgba(15,23,42,0.04)]">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="text-lg font-semibold">{viewTitle[view]}</h2>
              <p className="text-sm text-slate-500">
                状态 <b>{result?.status || (isRunning ? 'running' : '-')}</b>
                {' · '}
                Run <b>{runId || '-'}</b>
              </p>
            </div>
            <div className="flex flex-wrap gap-2">
              <button type="button" onClick={() => void onRefreshRun()} disabled={!runId || isRunning} className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm disabled:opacity-50">
                刷新运行
              </button>
              <button type="button" onClick={() => void onStopRun()} disabled={!runId} className="inline-flex items-center gap-1 rounded-xl border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700 hover:bg-red-100 disabled:opacity-50">
                <Square size={14} />停止
              </button>
            </div>
          </div>
        </section>
      ) : null}

      {view === 'creator' ? (
        <section className="rounded-xl border border-slate-200/80 bg-white p-5 shadow-[0_1px_2px_rgba(15,23,42,0.04)]">
          <div className="mb-4 flex items-start justify-between gap-3">
            <div>
              <h2 className="text-lg font-semibold">运行摘要</h2>
              <p className="text-sm text-slate-500">启动后可在监控、选题、编辑等页签查看详情。</p>
            </div>
            <div className="space-y-1 text-right text-xs text-slate-500">
              <div>状态：<b>{result?.status || (isRunning ? 'running' : '-')}</b></div>
              <div>Run ID：<b>{runId || '-'}</b></div>
            </div>
          </div>
          <div className="rounded-xl bg-slate-50 p-6">
            <div className="mb-2 text-xs uppercase tracking-[0.2em] text-slate-400">Title</div>
            <h3 className="text-2xl font-semibold leading-tight">{result?.title || '运行后这里会显示标题'}</h3>
            <p className="mt-4 line-clamp-6 whitespace-pre-wrap text-sm leading-7 text-slate-700">{body}</p>
          </div>
        </section>
      ) : null}

      {view === 'monitor' ? (
        <div className="grid gap-4 lg:grid-cols-2">
          <section className="rounded-xl border border-slate-200/80 bg-white p-5 shadow-[0_1px_2px_rgba(15,23,42,0.04)]">
            <div className="mb-3 flex items-center justify-between">
              <h2 className="text-lg font-semibold">系统状态</h2>
              <button type="button" onClick={() => void refreshStatus()} className="rounded-xl bg-slate-100 hover:bg-slate-200 px-3 py-2 text-sm">
                刷新
              </button>
            </div>
            <div className="space-y-2 text-sm text-slate-600">
              <Info label="整体状态" value={health?.status || '-'} />
              <Info label="文本模型" value={health?.llm_model || '-'} />
              <Info label="生图模型" value={health?.image_model || '-'} />
              <Info label="视觉模型" value={health?.vision_model || '-'} />
              <Info label="Postgres" value={health?.checks?.postgres_connectivity ? '已连通' : '未连通'} />
              <Info label="运行模式" value={Object.keys(capabilities?.run_modes ?? {}).join(' / ') || '-'} />
              <Info label="平台规则" value={platformRule?.label || platform} />
              <Info label="图片目标" value={formatImageTargets(platformRule?.image_targets)} />
            </div>
          </section>
          <section className="rounded-xl border border-slate-200/80 bg-white p-5 shadow-[0_1px_2px_rgba(15,23,42,0.04)]">
            <h2 className="mb-3 text-lg font-semibold">运行指标</h2>
            <div className="grid gap-3 sm:grid-cols-2">
              <MetricCard label="TTFT" value={ttftMs !== null ? `${ttftMs} ms` : '-'} />
              <MetricCard label="节点数" value={String((result?.trace ?? []).length)} />
              <MetricCard label="总耗时" value={formatMs(numberOf(result?.metrics_summary?.latency_ms))} />
              <MetricCard label="Tokens" value={String(numberOf(result?.metrics_summary?.total_tokens) ?? '-')} />
            </div>
            <p className="mt-3 truncate text-xs text-slate-500">Request ID：{requestId || '-'}</p>
          </section>
          <section className="rounded-xl border border-slate-200/80 bg-white p-5 shadow-[0_1px_2px_rgba(15,23,42,0.04)] lg:col-span-2">
            <h2 className="mb-3 text-lg font-semibold">结构化审核</h2>
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
              <Info label="总分" value={reviewTotal !== null ? `${reviewTotal} / 30` : '-'} />
              <Info label="分数线" value={`${reviewerThreshold} / 30`} />
              <Info label="结论" value={reviewPassed === null ? '-' : reviewPassed ? '通过' : '需重写'} />
              <Info label="吸引力" value={formatTenPoint(numberOf(review.attraction_score))} />
              <Info label="准确性" value={formatTenPoint(numberOf(review.accuracy_score))} />
              <Info label="平台适配" value={formatTenPoint(numberOf(review.platform_score))} />
              <Info label="审核反馈" value={asString(review.feedback) || '-'} />
            </div>
          </section>
          <section className="rounded-xl border border-slate-200/80 bg-white p-5 shadow-[0_1px_2px_rgba(15,23,42,0.04)] lg:col-span-2">
            <h2 className="mb-3 text-lg font-semibold">流程进度</h2>
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
              {(result?.trace ?? []).length ? (result?.trace ?? []).map((node, index) => (
                <div key={`${node}-${index}`} className="relative rounded-lg border border-slate-200 bg-white px-4 py-3 pl-9 shadow-[0_1px_1px_rgba(15,23,42,0.03)]">
                  <span className="absolute left-3 top-4 grid h-5 w-5 place-items-center rounded-full bg-teal-50 text-[10px] font-semibold text-teal-700 ring-1 ring-teal-100">{index + 1}</span>
                  <p className="text-sm font-medium text-slate-900">{labelOf(node)}</p>
                  <p className="mt-1 truncate text-xs text-slate-500">{node}</p>
                </div>
              )) : <div className="rounded-lg bg-slate-50 px-4 py-3 text-sm text-slate-500">运行开始后，这里会展示工作流经过的节点。</div>}
            </div>
          </section>
          <section className="rounded-xl border border-slate-200/80 bg-white p-5 shadow-[0_1px_2px_rgba(15,23,42,0.04)] lg:col-span-2">
            <h2 className="mb-3 text-lg font-semibold">事件流摘要</h2>
            <div className="grid gap-3 sm:grid-cols-2">
              {logs.length ? logs.map((item, index) => <div key={`${item}-${index}`} className="rounded-lg bg-slate-50 px-4 py-3 text-sm text-slate-700">{item}</div>) : <div className="rounded-lg bg-slate-50 px-4 py-3 text-sm text-slate-500">运行开始后，这里会展示 start / update / final 等事件摘要。</div>}
            </div>
          </section>
          <section className="rounded-xl border border-slate-200/80 bg-white p-5 shadow-[0_1px_2px_rgba(15,23,42,0.04)] lg:col-span-2">
            <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
              <div>
                <h2 className="text-lg font-semibold">节点详情</h2>
                <p className="text-sm text-slate-500">来自 /v2/runs/{runId || '{run_id}'}/nodes 的输入、输出、耗时、token 与错误摘要。</p>
              </div>
              <button type="button" onClick={() => void refreshNodeDetails()} disabled={!runId} className="rounded-xl bg-slate-100 hover:bg-slate-200 px-3 py-2 text-sm disabled:opacity-50">
                刷新节点
              </button>
            </div>
            <div className="mb-4 flex flex-wrap gap-2">
              {nodeDetails.length ? nodeDetails.map((item) => (
                <button
                  key={item.node}
                  type="button"
                  onClick={() => setSelectedNode(item.node)}
                  className={`rounded-full border px-3 py-1.5 text-xs ${selectedNode === item.node ? 'border-teal-700 bg-emerald-50 text-teal-700' : 'border-slate-200 bg-white text-slate-600'}`}
                >
                  {labelOf(item.node)}
                </button>
              )) : null}
            </div>
            {selectedNodeDetail ? (
              <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_320px]">
                <div className="space-y-3 rounded-xl border border-slate-200 bg-white p-4">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <h3 className="font-semibold">{labelOf(selectedNodeDetail.node)}</h3>
                    <span className="rounded-full bg-slate-100 px-3 py-1 text-xs text-slate-600">{selectedNodeDetail.status || '-'}</span>
                  </div>
                  <Info label="节点 ID" value={selectedNodeDetail.node || '-'} />
                  <Info label="耗时" value={formatMs(selectedNodeDetail.latency_ms)} />
                  <Info label="Tokens" value={String(selectedNodeDetail.total_tokens ?? 0)} />
                  <Info label="错误" value={selectedNodeDetail.error || '无'} />
                  <div>
                    <p className="mb-1 text-sm font-medium text-slate-700">输入摘要</p>
                    <p className="rounded-lg bg-white px-4 py-3 text-sm leading-6 text-slate-600">{selectedNodeDetail.input_summary || '-'}</p>
                  </div>
                  <div>
                    <p className="mb-1 text-sm font-medium text-slate-700">输出摘要</p>
                    <p className="rounded-lg bg-white px-4 py-3 text-sm leading-6 text-slate-600">{selectedNodeDetail.output_summary || '-'}</p>
                  </div>
                </div>
                <div className="space-y-3 rounded-xl border border-slate-200 bg-white p-4">
                  <h3 className="font-semibold">节点重跑</h3>
                  <textarea
                    value={nodeRerunInstruction}
                    onChange={(event) => setNodeRerunInstruction(event.target.value)}
                    rows={5}
                    placeholder="例如：保留当前选题，但把这个节点的输出改得更具体、更适合目标平台。"
                    className="w-full rounded-lg border border-slate-200 bg-white px-4 py-3 text-sm leading-6 outline-none focus:border-teal-700 focus:ring-2 focus:ring-teal-700/10"
                  />
                  <button type="button" onClick={() => void onRerunSelectedNode()} disabled={!runId || !selectedNodeDetail.node || isRunning} className="w-full rounded-lg bg-teal-700 hover:bg-teal-800 px-4 py-3 text-sm font-medium text-white disabled:opacity-50">
                    {isRunning ? '重跑中...' : '按当前节点重跑'}
                  </button>
                  <p className="text-xs leading-5 text-slate-500">当前实现会创建一个新的受控 rerun，不覆盖原 run，便于回查。</p>
                </div>
              </div>
            ) : (
              <div className="rounded-lg bg-slate-50 px-4 py-5 text-sm text-slate-500">运行完成或选择历史 run 后，这里会显示节点级详情。</div>
            )}
          </section>
        </div>
      ) : null}

      {view === 'topics' ? (
        <section className="rounded-xl border border-slate-200/80 bg-white p-5 shadow-[0_1px_2px_rgba(15,23,42,0.04)]">
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="text-lg font-semibold">选题决策</h2>
              <p className="text-sm text-slate-500">引导模式下选择候选选题后继续工作流。</p>
            </div>
            <button type="button" onClick={() => void onContinue()} disabled={selectedTopicIndex === null || !guidedTopics.length || isRunning} className="rounded-lg bg-teal-700 hover:bg-teal-800 px-4 py-3 text-sm font-medium text-white disabled:opacity-50">
              选题后继续
            </button>
          </div>
          {guidedTopics.length ? (
            <div className="grid gap-3">
              {guidedTopics.map((topic, index) => (
                <button key={`${topic.title}-${index}`} type="button" onClick={() => setSelectedTopicIndex(index)} className={`rounded-lg border px-4 py-4 text-left ${selectedTopicIndex === index ? 'border-amber-700 bg-amber-50' : 'border-slate-200 bg-white'}`}>
                  <div className="mb-2 flex items-center justify-between gap-2">
                    <p className="font-semibold">{topic.title}</p>
                    <span className="rounded-full bg-slate-100 px-2 py-1 text-xs text-slate-600">热度 {topic.heat_score ?? '-'}</span>
                  </div>
                  <p className="text-sm text-slate-600">{topic.reason || '暂无推荐理由'}</p>
                  {topic.content_angle ? <p className="mt-2 text-xs text-slate-500">角度：{topic.content_angle}</p> : null}
                </button>
              ))}
            </div>
          ) : (
            <div className="rounded-lg bg-slate-50 px-4 py-5 text-sm text-slate-500">
              {(result?.research_topics ?? []).length
                ? '当前运行未处于选题等待状态；可在创作页以 guided 模式重新运行。'
                : '运行引导模式并进入 awaiting_topic_selection 后，这里会出现候选选题。'}
            </div>
          )}
        </section>
      ) : null}

      {view === 'editor' ? (
        <section className="space-y-4">
          <div className="rounded-xl border border-slate-200/80 bg-white p-5 shadow-[0_1px_2px_rgba(15,23,42,0.04)]">
            <div className="mb-4 rounded-xl bg-slate-50 p-6">
              <div className="mb-2 text-xs uppercase tracking-[0.2em] text-slate-400">Title</div>
              <h3 className="text-3xl font-semibold leading-tight">{result?.title || '运行后这里会显示标题'}</h3>
              <div className="mt-3 flex flex-wrap gap-2">
                {(result?.tags ?? []).map((tag) => <span key={tag} className="rounded-full bg-white px-3 py-1 text-xs text-slate-600 ring-1 ring-black/5">{tag}</span>)}
              </div>
            </div>
            <article className="rounded-xl border border-slate-200 bg-white p-6">
              <div className="mb-3 text-sm font-medium text-slate-600">正文内容</div>
              <div className="whitespace-pre-wrap text-[16px] leading-8 text-slate-800">{body}</div>
            </article>
          </div>
          <div className="rounded-xl border border-slate-200/80 bg-white p-5 shadow-[0_1px_2px_rgba(15,23,42,0.04)]">
            <h3 className="mb-3 font-semibold">结构化审核</h3>
            <div className="mb-4 grid gap-2 rounded-lg bg-slate-50 p-4 text-sm text-slate-600 sm:grid-cols-2">
              <Info label="总分" value={reviewTotal !== null ? `${reviewTotal} / 30` : '-'} />
              <Info label="结论" value={reviewPassed === null ? '-' : reviewPassed ? '通过' : '需重写'} />
              <Info label="吸引力" value={formatTenPoint(numberOf(review.attraction_score))} />
              <Info label="准确性" value={formatTenPoint(numberOf(review.accuracy_score))} />
              <Info label="平台适配" value={formatTenPoint(numberOf(review.platform_score))} />
              <Info label="反馈" value={asString(review.feedback) || '-'} />
            </div>
            <h3 className="mb-3 font-semibold">按指令重写</h3>
            <p className="mb-3 text-sm text-slate-500">调用 /v2/run/rewrite，基于当前 Run 与修改指令重新生成内容。</p>
            <textarea
              value={rewriteInstruction}
              onChange={(e) => setRewriteInstruction(e.target.value)}
              rows={4}
              placeholder="例如：缩短开头，增加两个具体案例，语气更克制。"
              className="mb-3 w-full rounded-lg border border-slate-200 bg-white px-4 py-3 text-sm leading-6 outline-none focus:border-teal-700 focus:ring-2 focus:ring-teal-700/10"
            />
            <button type="button" onClick={() => void onRewrite()} disabled={!runId || isRunning} className="rounded-lg bg-teal-700 hover:bg-teal-800 px-4 py-3 text-sm font-medium text-white disabled:opacity-50">
              {isRunning ? <Loader2 size={16} className="inline animate-spin" /> : null} 提交重写
            </button>
          </div>
        </section>
      ) : null}

      {view === 'assets' ? (
        <section className="space-y-4">
          <div className="rounded-xl border border-slate-200/80 bg-white p-5 shadow-[0_1px_2px_rgba(15,23,42,0.04)]">
            <div className="mb-3 flex items-center justify-between">
              <h2 className="text-lg font-semibold">主图与视觉质检</h2>
              <span className="rounded-full bg-slate-100 px-3 py-1 text-xs text-slate-600">候选 {covers.length} 张</span>
            </div>
            <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_320px]">
              {mainCover?.web_path || mainCover?.image_url ? <img src={mainCover.web_path || mainCover.image_url} alt={result?.title || 'cover'} className="h-[280px] w-full rounded-lg object-cover" /> : <div className="flex h-[280px] items-center justify-center rounded-lg bg-slate-50 text-sm text-slate-500">当前还没有主图</div>}
              <div className="grid gap-2 text-sm text-slate-600">
                <Info label="模型" value={mainCover?.model || '-'} />
                <Info label="尺寸" value={mainCover?.requested_size || '-'} />
                <Info label="视觉质检分" value={formatScore(result?.cover_visual_review?.overall_score)} />
                <Info label="图文一致性" value={formatConsistency(result?.text_image_consistency?.score)} />
                <Info label="风险项" value={(result?.cover_visual_review?.risk_flags ?? []).join(' / ') || '无'} />
              </div>
            </div>
            {result?.cover_visual_review?.feedback ? <div className="mt-3 rounded-lg bg-slate-50 px-4 py-3 text-sm text-slate-700">{result.cover_visual_review.feedback}</div> : null}
            <div className="mt-4 grid gap-3 rounded-lg border border-slate-200 bg-white p-4 lg:grid-cols-[minmax(0,1fr)_auto]">
              <label className="block">
                <span className="mb-2 block text-sm font-medium text-slate-700">封面替换 URL</span>
                <input
                  value={coverReplacementUrl}
                  onChange={(event) => setCoverReplacementUrl(event.target.value)}
                  placeholder="可粘贴审核通过的封面图 URL，发布清单会同步使用"
                  className="w-full rounded-lg border border-slate-200 bg-white px-4 py-3 text-sm outline-none focus:border-teal-700"
                />
              </label>
              <button type="button" onClick={() => void applyCoverReplacement()} disabled={!mainCover || isRunning} className="self-end rounded-xl bg-teal-700 hover:bg-teal-800 px-3 py-3 text-sm text-white disabled:opacity-50">
                保存封面
              </button>
              <button type="button" onClick={() => setCoverReplacementUrl('')} className="self-end rounded-xl border border-slate-200 bg-white px-3 py-3 text-sm text-slate-700">
                恢复封面
              </button>
            </div>
          </div>
          <div className="rounded-xl border border-slate-200/80 bg-white p-5 shadow-[0_1px_2px_rgba(15,23,42,0.04)]">
            <div className="mb-3 flex items-center justify-between">
              <h3 className="font-semibold">候选封面图</h3>
            </div>
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
              {covers.length ? covers.map((cover, index) => (
                <button key={`${cover.web_path || cover.image_url || 'cover'}-${index}`} type="button" onClick={() => setSelectedCoverIndex(index)} className={`overflow-hidden rounded-lg border ${selectedCoverIndex === index ? 'border-teal-700' : 'border-slate-200'}`}>
                  {cover.web_path || cover.image_url ? <img src={cover.web_path || cover.image_url} alt={`候选封面 ${index + 1}`} className="h-36 w-full object-cover" /> : <div className="flex h-36 items-center justify-center bg-slate-50 text-sm text-slate-500">无封面</div>}
                  <div className="flex items-center justify-between px-3 py-2 text-xs text-slate-600"><span>{cover.is_primary ? '主图' : `候选 ${index + 1}`}</span><span>{formatMs(cover.latency_ms)}</span></div>
                </button>
              )) : <div className="rounded-lg bg-slate-50 px-4 py-5 text-sm text-slate-500">运行完成后这里会展示候选封面。</div>}
            </div>
          </div>
          <div className="rounded-xl border border-slate-200/80 bg-white p-5 shadow-[0_1px_2px_rgba(15,23,42,0.04)]">
            <div className="mb-3 flex items-center justify-between">
              <h3 className="font-semibold">图片素材管理</h3>
              <span className="rounded-full bg-slate-100 px-3 py-1 text-xs text-slate-600">共 {effectiveImageAssets.length} 个素材</span>
            </div>
            <div className="mb-4 grid gap-4 rounded-xl border border-slate-200 bg-white p-4 lg:grid-cols-[260px_minmax(0,1fr)]">
              <div>
                {selectedAssetUrl ? (
                  <img src={selectedAssetUrl} alt={selectedAsset?.usage || 'selected asset'} className="h-44 w-full rounded-lg object-cover" />
                ) : (
                  <div className="flex h-44 items-center justify-center rounded-lg bg-slate-50 text-sm text-slate-500">请选择素材</div>
                )}
              </div>
              <div className="space-y-3">
                <div className="grid gap-2 text-sm text-slate-600 sm:grid-cols-2">
                  <Info label="当前素材" value={selectedAsset?.usage || selectedAsset?.asset_type || '-'} />
                  <Info label="来源模型" value={selectedAsset?.model || '-'} />
                  <Info label="状态" value={selectedAsset?.status || '-'} />
                  <Info label="尺寸" value={selectedAsset?.requested_size || '-'} />
                </div>
                <label className="block">
                  <span className="mb-2 block text-sm font-medium text-slate-700">替换预览 URL</span>
                  <input
                    value={replacementImageUrl}
                    onChange={(event) => setReplacementImageUrl(event.target.value)}
                    placeholder="粘贴一张审核通过的图片 URL，应用后会进入发布清单"
                    className="w-full rounded-lg border border-slate-200 bg-white px-4 py-3 text-sm outline-none focus:border-teal-700"
                  />
                </label>
                <div className="flex flex-wrap gap-2">
                  <button type="button" onClick={() => void applyAssetReplacement()} disabled={!selectedAsset || isRunning} className="rounded-xl bg-teal-700 hover:bg-teal-800 px-3 py-2 text-sm text-white disabled:opacity-50">
                    应用到发布清单
                  </button>
                  <button type="button" onClick={resetAssetReplacement} className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm text-slate-700">
                    恢复原图
                  </button>
                  {selectedAssetUrl ? <a href={selectedAssetUrl} download className="inline-flex items-center gap-1 rounded-xl bg-slate-100 hover:bg-slate-200 px-3 py-2 text-sm text-slate-700"><PackageCheck size={14} />下载/打开</a> : null}
                </div>
              </div>
            </div>
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
              {effectiveImageAssets.length ? effectiveImageAssets.map((asset, index) => (
                <button
                  key={`${asset.web_path || asset.image_url || 'asset'}-${index}`}
                  type="button"
                  onClick={() => setSelectedAssetIndex(index)}
                  className={`overflow-hidden rounded-lg border bg-white text-left ${selectedAssetIndex === index ? 'border-teal-700 ring-2 ring-teal-700/15' : 'border-slate-200'}`}
                >
                  {asset.web_path || asset.image_url ? <img src={asset.web_path || asset.image_url} alt={asset.usage || `素材 ${index + 1}`} className="h-36 w-full object-cover" /> : <div className="flex h-36 items-center justify-center bg-slate-50 text-sm text-slate-500">无图片</div>}
                  <div className="space-y-1 px-3 py-3 text-xs text-slate-600">
                    <div className="font-medium text-slate-800">{asset.usage || asset.asset_type || `素材 ${index + 1}`}</div>
                    <div>{asset.model || '-'} / {asset.requested_size || '-'}</div>
                    <span className="inline-flex items-center gap-1 text-teal-700">{selectedAssetIndex === index ? '已选中' : '选择素材'}</span>
                  </div>
                </button>
              )) : <div className="rounded-lg bg-slate-50 px-4 py-5 text-sm text-slate-500">运行后这里会展示封面、正文配图、卡片图和总结卡。</div>}
            </div>
          </div>
        </section>
      ) : null}

      {view === 'publish' ? (
        <section className="rounded-xl border border-slate-200/80 bg-white p-5 shadow-[0_1px_2px_rgba(15,23,42,0.04)]">
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="text-lg font-semibold">发布准备包</h2>
              <p className="text-sm text-slate-500">{platformRule?.content_shape || '按平台规则生成标题、正文、标签和图片清单。'}</p>
            </div>
            <span className="rounded-full bg-slate-100 px-3 py-1 text-xs text-slate-600">{publishPackage?.platform || platform}</span>
          </div>
          {platformRule ? (
            <div className="mb-4 grid gap-2 rounded-lg bg-slate-50 p-4 text-sm text-slate-600 sm:grid-cols-2">
              <Info label="篇幅提示" value={platformRule.length_hint || '-'} />
              <Info label="段落提示" value={platformRule.paragraph_hint || '-'} />
              <Info label="语气提示" value={platformRule.tone_hint || '-'} />
              <Info label="标签数量" value={platformRule.tag_count || '-'} />
            </div>
          ) : null}
          <div className="grid gap-3 xl:grid-cols-3">
            <CopyBlock label="标题" value={publishPackage?.copy_blocks?.title || result?.title || ''} onCopy={copyText} />
            <CopyBlock label="正文" value={publishPackage?.copy_blocks?.body || result?.content || ''} onCopy={copyText} />
            <CopyBlock label="标签" value={publishPackage?.copy_blocks?.tags || (result?.tags ?? []).join(' ')} onCopy={copyText} />
          </div>
          <div className="mt-4 grid gap-4 lg:grid-cols-2">
            <Checklist title="平台发布检查" items={publishPackage?.checks ?? platformRule?.publish_checks ?? []} />
            <Checklist title="半自动发布步骤" items={publishPackage?.manual_steps ?? platformRule?.publish_steps ?? []} />
          </div>
          <div className="mt-4 rounded-lg border border-slate-200 bg-white p-4 text-sm text-slate-600">
            <h3 className="mb-3 font-semibold text-slate-800">自动发布边界</h3>
            <Info label="官方 API 优先" value={publishPackage?.automation_research?.official_api_first ? '是' : '待确认'} />
            <Info label="不保存密码" value={publishPackage?.automation_research?.no_password_storage ? '是' : '是'} />
            <Info label="不绕过验证码" value={publishPackage?.automation_research?.no_captcha_bypass ? '是' : '是'} />
            <Info label="当前状态" value={asString(publishPackage?.automation_research?.status) || 'prepared_package_only'} />
            <p className="mt-3 leading-6">{asString(publishPackage?.automation_research?.note) || '先交付发布准备包；仅在平台提供官方开放能力时再接自动发布。'}</p>
          </div>
          <div className="mt-4 rounded-lg border border-slate-200 bg-white p-4">
            <div className="mb-3 flex items-center justify-between gap-3">
              <h3 className="font-semibold">发布图片清单</h3>
              <span className="rounded-full bg-slate-100 px-3 py-1 text-xs text-slate-600">
                共 {publishImageAssets.length} 张
              </span>
            </div>
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
              {publishImageAssets.length ? publishImageAssets.map((asset, index) => {
                const baseAsset = publishPackage?.image_assets?.[index];
                const mergedAsset = baseAsset ? { ...baseAsset, ...asset } : asset;
                const url = mergedAsset.web_path || mergedAsset.image_url || '';
                return (
                  <div key={`${url || mergedAsset.usage || 'publish-image'}-${index}`} className="overflow-hidden rounded-lg border border-slate-200 bg-white">
                    {url ? <img src={url} alt={mergedAsset.usage || `发布图片 ${index + 1}`} className="h-32 w-full object-cover" /> : <div className="flex h-32 items-center justify-center bg-slate-50 text-sm text-slate-500">无图片</div>}
                    <div className="space-y-1 px-3 py-3 text-xs text-slate-600">
                      <div className="font-medium text-slate-800">{mergedAsset.usage || mergedAsset.asset_type || `图片 ${index + 1}`}</div>
                      <div>{mergedAsset.status || '-'} / {mergedAsset.requested_size || '-'}</div>
                      {url ? <a href={url} download className="inline-flex items-center gap-1 text-teal-700"><PackageCheck size={13} />下载/打开</a> : null}
                    </div>
                  </div>
                );
              }) : <div className="rounded-lg bg-slate-50 px-4 py-5 text-sm text-slate-500">运行完成后，这里会列出发布前需要上传的全部图片。</div>}
            </div>
          </div>
        </section>
      ) : null}

      {view === 'history' ? (
        <>
          <aside className="rounded-xl border border-slate-200/80 bg-white p-5 shadow-[0_1px_2px_rgba(15,23,42,0.04)]">
            <div className="mb-4 flex items-center justify-between">
              <div>
                <h2 className="text-lg font-semibold">运行历史</h2>
                <p className="text-sm text-slate-500">优先展示服务端 /v2/runs，失败时回退本地缓存。</p>
              </div>
              <button type="button" onClick={() => void refreshHistory()} disabled={historyLoading} className="rounded-xl bg-slate-100 hover:bg-slate-200 px-3 py-2 text-sm disabled:opacity-60">
                {historyLoading ? '刷新中…' : '刷新'}
              </button>
            </div>
            <div className="space-y-2">
              {historyRuns.length ? historyRuns.map((entry) => (
                <button
                  key={entry.run_id}
                  type="button"
                  onClick={() => void onLoadHistoryRun(entry.run_id)}
                  className={`w-full rounded-lg border px-4 py-3 text-left ${runId === entry.run_id ? 'border-teal-700 bg-emerald-50' : 'border-slate-200 bg-white'}`}
                >
                  <p className="font-medium text-slate-800">{entry.title || entry.run_id}</p>
                  <p className="mt-1 text-xs text-slate-500">{entry.status || '-'} · {entry.platform || '-'} · {entry.created_at ? new Date(entry.created_at).toLocaleString() : '-'}</p>
                </button>
              )) : <div className="rounded-lg bg-slate-50 px-4 py-5 text-sm text-slate-500">暂无历史记录，完成一次运行后会出现在这里。</div>}
            </div>
          </aside>
          <section className="rounded-xl border border-slate-200/80 bg-white p-5 shadow-[0_1px_2px_rgba(15,23,42,0.04)]">
            <h2 className="mb-3 text-lg font-semibold">回查详情</h2>
            {result ? (
              <div className="space-y-4">
                <div className="grid gap-2 text-sm text-slate-600 sm:grid-cols-2">
                  <Info label="Run ID" value={runId || '-'} />
                  <Info label="状态" value={result.status || '-'} />
                  <Info label="平台" value={result.platform || platform} />
                  <Info label="风格" value={result.style || style} />
                </div>
                <div className="rounded-xl bg-slate-50 p-6">
                  <h3 className="text-2xl font-semibold">{result.title || '(无标题)'}</h3>
                  <p className="mt-4 line-clamp-[12] whitespace-pre-wrap text-sm leading-7 text-slate-700">{body}</p>
                </div>
                <button type="button" onClick={() => void onRefreshRun()} disabled={!runId || isRunning} className="rounded-lg border border-slate-200 bg-white px-4 py-3 text-sm font-medium disabled:opacity-50">
                  从服务端刷新此 Run
                </button>
              </div>
            ) : (
              <div className="rounded-lg bg-slate-50 px-4 py-5 text-sm text-slate-500">从左侧选择一条运行记录查看详情。</div>
            )}
          </section>
        </>
      ) : null}
    </div>
  );
}

function Select(props: { label: string; value: string; onChange: (v: string) => void; options: string[]; labels?: Record<string, string> }) {
  return <label className="block"><span className="mb-2 block text-sm font-medium">{props.label}</span><select value={props.value} onChange={(e) => props.onChange(e.target.value)} className="w-full rounded-lg border border-slate-200 bg-white px-4 py-3 text-sm outline-none focus:border-teal-700 focus:ring-2 focus:ring-teal-700/10">{props.options.map((option) => <option key={option} value={option}>{props.labels?.[option] ?? option}</option>)}</select></label>;
}

function NumberField(props: { label: string; value: number; onChange: (v: number) => void; min: number; max: number }) {
  return <label className="block"><span className="mb-2 block text-sm font-medium">{props.label}</span><input type="number" min={props.min} max={props.max} value={props.value} onChange={(e) => props.onChange(Number(e.target.value))} className="w-full rounded-lg border border-slate-200 bg-white px-4 py-3 text-sm outline-none focus:border-teal-700 focus:ring-2 focus:ring-teal-700/10" /></label>;
}

function Info(props: { label: string; value: string }) {
  return <div className="flex items-center justify-between gap-4 rounded-md px-1 py-1"><span className="text-slate-500">{props.label}</span><span className="text-right font-medium text-slate-900">{props.value}</span></div>;
}

function MetricCard(props: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-slate-50 px-4 py-3">
      <div className="text-xs font-medium text-slate-500">{props.label}</div>
      <div className="mt-1 truncate text-lg font-semibold tracking-tight text-slate-950">{props.value}</div>
    </div>
  );
}

function CopyBlock(props: { label: string; value: string; onCopy: (text: string, label: string) => Promise<void> }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-[0_1px_1px_rgba(15,23,42,0.03)]">
      <div className="mb-2 flex items-center justify-between gap-2">
        <span className="text-sm font-medium text-slate-700">{props.label}</span>
        <button type="button" onClick={() => void props.onCopy(props.value, props.label)} disabled={!props.value} className="inline-flex items-center gap-1 rounded-md bg-slate-100 px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-200 disabled:opacity-50">
          <Clipboard size={13} />复制
        </button>
      </div>
      <div className="max-h-80 min-h-[84px] overflow-auto whitespace-pre-wrap text-sm leading-6 text-slate-600">
        {props.value || '运行完成后生成'}
      </div>
    </div>
  );
}

function Checklist(props: { title: string; items: string[] }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-slate-50 p-4">
      <h4 className="mb-3 text-sm font-semibold text-slate-800">{props.title}</h4>
      <div className="space-y-2">
        {props.items.length ? props.items.map((item) => (
          <label key={item} className="flex items-start gap-2 text-sm text-slate-700">
            <input type="checkbox" className="mt-1" />
            <span>{item}</span>
          </label>
        )) : <p className="text-sm text-slate-500">运行完成后生成检查项。</p>}
      </div>
    </div>
  );
}

function toggleFormat(current: string[], format: string): string[] {
  if (current.includes(format)) {
    const next = current.filter((item) => item !== format);
    return next.length ? next : ['json'];
  }
  return [...current, format];
}

function mapToggle(value: MockToggle): boolean | undefined {
  if (value === 'default') return undefined;
  return value === 'mock';
}

function labelOf(node: string): string {
  const mapping: Record<string, string> = { brief_intake: '接收需求', research_topic: '研究选题', research_evidence_merge: '整理素材', write_draft: '起草正文', adapt_platform: '平台适配', plan_cover: '封面策划', generate_cover: '生成封面', review_cover_visual: '封面视觉质检', review_structured: '结构化审核', review_route: '审核路由', approval_gate: '审批环节', export: '导出结果' };
  return mapping[node] ?? node;
}

function formatMs(value?: number | null): string {
  return typeof value === 'number' && !Number.isNaN(value) ? `${Math.round(value)} ms` : '-';
}

function formatScore(value?: number): string {
  return typeof value === 'number' ? `${value} / 100` : '-';
}

function formatConsistency(value?: number): string {
  return typeof value === 'number' ? `${Math.round(value * 100)}%` : '-';
}

function formatTenPoint(value?: number | null): string {
  return typeof value === 'number' && !Number.isNaN(value) ? `${value} / 10` : '-';
}

function formatImageTargets(targets?: Record<string, number>): string {
  if (!targets) return '-';
  return Object.entries(targets)
    .filter(([, count]) => Number(count) > 0)
    .map(([key, count]) => `${key}:${count}`)
    .join(' / ') || '-';
}

function messageOf(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback;
}

function asString(value: unknown): string {
  return typeof value === 'string' ? value : '';
}

function numberOf(value: unknown): number | null {
  return typeof value === 'number' ? value : null;
}


