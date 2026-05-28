import { useEffect, useState, type ReactNode } from 'react';
import { Lock, Search } from 'lucide-react';
import {
  getHealth,
  getRun,
  getAdminLogs,
  getWorkflowCapabilities,
  listRuns,
  loadRunHistory,
  type HealthPayload,
  type WorkflowCapabilities,
  type WorkflowResult,
} from '../lib/mediaAgentApi';

export default function AdminDashboard() {
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [health, setHealth] = useState<HealthPayload | null>(null);
  const [capabilities, setCapabilities] = useState<WorkflowCapabilities | null>(null);
  const [lookupRunId, setLookupRunId] = useState('');
  const [selectedRun, setSelectedRun] = useState<WorkflowResult | null>(null);
  const [recentRuns, setRecentRuns] = useState(loadRunHistory());
  const [logs, setLogs] = useState<Record<string, unknown>[]>([]);

  useEffect(() => {
    if (!isAuthenticated) return;
    void refreshDashboard();
  }, [isAuthenticated]);

  function handleLogin(event: React.FormEvent) {
    event.preventDefault();
    if (password === 'ztk123') {
      setIsAuthenticated(true);
      setError('');
      return;
    }
    setError('密码错误，请输入 ztk123');
  }

  async function refreshDashboard() {
    try {
      const [healthPayload, capabilityPayload, runList, logPayload] = await Promise.all([
        getHealth(),
        getWorkflowCapabilities(),
        listRuns(30),
        getAdminLogs(60),
      ]);
      setHealth(healthPayload);
      setCapabilities(capabilityPayload);
      setRecentRuns(runList.items.length ? runList.items : loadRunHistory());
      setLogs(logPayload.items);
    } catch (refreshError) {
      setError(refreshError instanceof Error ? refreshError.message : '后台状态刷新失败');
    }
  }

  async function fetchRun(runId: string) {
    try {
      const result = await getRun(runId);
      setSelectedRun(result);
      setLookupRunId(runId);
      setError('');
    } catch (runError) {
      setError(runError instanceof Error ? runError.message : '运行记录查询失败');
    }
  }

  if (!isAuthenticated) {
    return (
      <div className="flex min-h-[calc(100vh-110px)] items-center justify-center">
        <div className="w-full max-w-md rounded-xl border border-slate-200/80 bg-white p-8 shadow-[0_20px_50px_rgba(15,23,42,0.08)]">
          <div className="mb-6 flex justify-center">
            <div className="rounded-full bg-amber-50 p-4 text-amber-700">
              <Lock size={28} />
            </div>
          </div>
          <h2 className="mb-2 text-center text-2xl font-semibold">后台管理</h2>
          <p className="mb-6 text-center text-sm text-slate-500">输入密码后查看系统状态、运行记录与质检摘要。</p>
          <form onSubmit={handleLogin} className="space-y-4">
            <input
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              placeholder="请输入后台密码"
              className="w-full rounded-lg border border-slate-200 bg-white px-4 py-3 outline-none focus:border-teal-700 focus:ring-2 focus:ring-teal-700/10"
            />
            {error ? <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div> : null}
            <button type="submit" className="w-full rounded-lg bg-teal-700 hover:bg-teal-800 px-4 py-3 font-medium text-white">
              进入后台
            </button>
          </form>
        </div>
      </div>
    );
  }

  return (
    <div className="grid gap-4 lg:grid-cols-[320px_minmax(0,1fr)]">
      <aside className="rounded-xl border border-slate-200/80 bg-white p-5 shadow-[0_1px_2px_rgba(15,23,42,0.04)]">
        <div className="mb-4 flex items-center justify-between">
          <div>
            <h2 className="text-lg font-semibold">后台总览</h2>
            <p className="text-sm text-slate-500">系统状态 + 本地保存的最近运行记录。</p>
          </div>
          <button type="button" onClick={() => void refreshDashboard()} className="rounded-xl bg-slate-100 hover:bg-slate-200 px-3 py-2 text-sm">
            刷新
          </button>
        </div>

          <div className="space-y-2 rounded-xl bg-slate-50 p-4 text-sm text-slate-600">
          <Info label="整体状态" value={health?.status || '-'} />
          <Info label="文本模型" value={health?.llm_model || '-'} />
          <Info label="生图模型" value={health?.image_model || '-'} />
          <Info label="视觉模型" value={health?.vision_model || '-'} />
          <Info label="Postgres" value={health?.checks?.postgres_connectivity ? '已连通' : '未连通'} />
          <Info label="运行模式" value={Object.keys(capabilities?.run_modes ?? {}).join(' / ') || '-'} />
          <Info label="平台规则" value={String((capabilities?.platform_rules ?? []).length || 0)} />
        </div>

        <div className="mt-5">
          <label className="mb-2 block text-sm font-medium text-slate-700">按 Run ID 查询</label>
          <div className="flex gap-2">
            <input
              value={lookupRunId}
              onChange={(event) => setLookupRunId(event.target.value)}
              placeholder="请输入 run_id"
              className="flex-1 rounded-lg border border-slate-200 bg-white px-4 py-3 text-sm outline-none focus:border-teal-700 focus:ring-2 focus:ring-teal-700/10"
            />
            <button
              type="button"
              onClick={() => void fetchRun(lookupRunId)}
              className="rounded-lg bg-teal-700 hover:bg-teal-800 px-4 py-3 text-white"
            >
              <Search size={16} />
            </button>
          </div>
        </div>

        <div className="mt-5">
          <h3 className="mb-3 text-sm font-semibold text-slate-800">最近任务</h3>
          <div className="space-y-3">
            {recentRuns.length ? recentRuns.map((item) => (
              <button
                key={item.run_id}
                type="button"
                onClick={() => void fetchRun(item.run_id)}
                className="w-full rounded-lg border border-slate-200 px-4 py-3 text-left transition hover:bg-slate-50"
              >
                <p className="truncate text-sm font-medium text-slate-800">{item.title || '(无标题)'}</p>
                <p className="mt-1 text-xs text-slate-500">{item.run_id}</p>
                <p className="mt-1 text-xs text-slate-500">{item.status || '-'}</p>
                <p className="mt-1 text-xs text-slate-500">素材 {item.image_count ?? 0} / 发布包 {item.publish_ready ? '可用' : '待生成'}</p>
              </button>
            )) : (
              <div className="rounded-lg bg-slate-50 px-4 py-3 text-sm text-slate-500">
                当前没有历史任务列表接口，这里先展示前端本地保存的最近运行记录。
              </div>
            )}
          </div>
        </div>
      </aside>

      <section className="space-y-4">
        <div className="rounded-xl border border-slate-200/80 bg-white p-5 shadow-[0_1px_2px_rgba(15,23,42,0.04)]">
          <h2 className="mb-4 text-lg font-semibold">运行详情</h2>
          {selectedRun ? (
            <div className="grid gap-4 xl:grid-cols-[minmax(0,1.1fr)_minmax(320px,0.9fr)]">
              <div className="space-y-4">
                <Panel title="基本信息">
                  <Info label="Run ID" value={selectedRun.run_id || '-'} />
                  <Info label="Request ID" value={selectedRun.request_id || '-'} />
                  <Info label="状态" value={selectedRun.status || '-'} />
                  <Info label="平台" value={selectedRun.platform || '-'} />
                  <Info label="风格" value={selectedRun.style || '-'} />
                </Panel>
                <Panel title="正文摘要">
                  <p className="text-sm leading-7 text-slate-700">{selectedRun.content || '暂无正文'}</p>
                </Panel>
                <Panel title="流程轨迹">
                  <div className="flex flex-wrap gap-2">
                    {(selectedRun.trace ?? []).map((node) => (
                      <span key={node} className="rounded-full bg-slate-100 px-3 py-1 text-xs text-slate-700">
                        {node}
                      </span>
                    ))}
                  </div>
                </Panel>
                <Panel title="发布准备包">
                  <Info label="标题" value={selectedRun.publish_package?.copy_blocks?.title || selectedRun.title || '-'} />
                  <Info label="图片素材" value={String(selectedRun.publish_package?.image_assets?.length ?? selectedRun.image_assets?.length ?? 0)} />
                  <Info label="检查项" value={String(selectedRun.publish_package?.checks?.length ?? 0)} />
                </Panel>
              </div>

              <div className="space-y-4">
                <Panel title="视觉质检摘要">
                  <Info label="总分" value={formatScore(selectedRun.cover_visual_review?.overall_score)} />
                  <Info label="是否通过" value={selectedRun.cover_visual_review?.passed ? '是' : '否'} />
                  <Info label="风险项" value={(selectedRun.cover_visual_review?.risk_flags ?? []).join(' / ') || '无'} />
                  <div className="mt-3 rounded-lg bg-slate-50 px-4 py-3 text-sm text-slate-700">
                    {selectedRun.cover_visual_review?.feedback || '暂无反馈'}
                  </div>
                </Panel>
                <Panel title="图文一致性摘要">
                  <Info label="状态" value={selectedRun.text_image_consistency?.status || '-'} />
                  <Info label="得分" value={formatConsistency(selectedRun.text_image_consistency?.score)} />
                  <Info label="匹配关键词" value={(selectedRun.text_image_consistency?.matched_keywords ?? []).slice(0, 6).join(' / ') || '无'} />
                </Panel>
                <Panel title="封面主图">
                  {selectedRun.image_asset?.web_path || selectedRun.image_asset?.image_url ? (
                    <img
                      src={selectedRun.image_asset.web_path || selectedRun.image_asset.image_url}
                      alt={selectedRun.title || 'cover'}
                      className="h-56 w-full rounded-lg object-cover"
                    />
                  ) : (
                    <div className="flex h-56 items-center justify-center rounded-lg bg-slate-50 text-sm text-slate-500">
                      当前无封面
                    </div>
                  )}
                </Panel>
                <Panel title="运行日志摘要">
                  <div className="max-h-64 space-y-2 overflow-auto">
                    {logs.slice(-8).map((entry, index) => (
                      <div key={index} className="rounded-lg bg-slate-50 px-3 py-2 text-xs text-slate-600">
                        {String(entry.event || entry.message || entry.msg || entry._source || 'log')}
                      </div>
                    ))}
                  </div>
                </Panel>
              </div>
            </div>
          ) : (
            <div className="rounded-xl bg-slate-50 px-5 py-8 text-sm text-slate-500">
              先从左侧最近任务里选择一条，或输入一个 run_id 进行查询。
            </div>
          )}
        </div>
      </section>
    </div>
  );
}

function Panel(props: { title: string; children: ReactNode }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-5">
      <h3 className="mb-3 text-sm font-semibold text-slate-800">{props.title}</h3>
      {props.children}
    </div>
  );
}

function Info(props: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-4 text-sm">
      <span className="text-slate-500">{props.label}</span>
      <span className="text-right font-medium text-slate-800">{props.value}</span>
    </div>
  );
}

function formatScore(value?: number) {
  return typeof value === 'number' ? `${value} / 100` : '-';
}

function formatConsistency(value?: number) {
  return typeof value === 'number' ? `${Math.round(value * 100)}%` : '-';
}

