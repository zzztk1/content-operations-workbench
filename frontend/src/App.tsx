import { useState, type ReactNode } from 'react';
import { BarChart3, CheckCircle2, Clock3, Edit3, FileCheck2, Image, LayoutDashboard, Settings, Sparkles } from 'lucide-react';
import CreatorStudio from './components/CreatorStudio';
import AdminDashboard from './components/AdminDashboard';

function App() {
  const [view, setView] = useState<'creator' | 'monitor' | 'topics' | 'editor' | 'assets' | 'publish' | 'history' | 'admin'>('creator');
  const creatorView = view === 'admin' ? 'creator' : view;

  return (
    <div className="min-h-screen bg-[var(--workbench-bg)] text-slate-950">
      <header className="sticky top-0 z-40 border-b border-slate-200/80 bg-white/90 backdrop-blur-xl">
        <div className="mx-auto flex max-w-[1760px] items-center gap-5 px-5 py-3.5">
          <div className="flex min-w-[250px] items-center gap-3">
            <div className="relative grid h-10 w-10 place-items-center rounded-xl border border-slate-200 bg-slate-950 text-white shadow-[0_8px_24px_rgba(15,23,42,0.12)]">
              <Sparkles size={18} />
              <span className="absolute -right-1 -top-1 h-3 w-3 rounded-full border-2 border-white bg-emerald-400" />
            </div>
            <div>
              <h1 className="text-[17px] font-semibold tracking-tight text-slate-950">智能内容运营工作台</h1>
              <p className="text-xs text-slate-500">选题、创作、素材、发布与回查</p>
            </div>
          </div>

          <nav className="min-w-0 flex-1 overflow-x-auto">
            <div className="inline-flex min-w-max items-center gap-1 rounded-xl border border-slate-200 bg-slate-100/80 p-1">
            <NavButton active={view === 'creator'} icon={<Sparkles size={15} />} label="创作" onClick={() => setView('creator')} />
            <NavButton active={view === 'monitor'} icon={<BarChart3 size={15} />} label="监控" onClick={() => setView('monitor')} />
            <NavButton active={view === 'topics'} icon={<LayoutDashboard size={15} />} label="选题" onClick={() => setView('topics')} />
            <NavButton active={view === 'editor'} icon={<Edit3 size={15} />} label="编辑" onClick={() => setView('editor')} />
            <NavButton active={view === 'assets'} icon={<Image size={15} />} label="素材" onClick={() => setView('assets')} />
            <NavButton active={view === 'publish'} icon={<FileCheck2 size={15} />} label="发布" onClick={() => setView('publish')} />
            <NavButton active={view === 'history'} icon={<Clock3 size={15} />} label="历史" onClick={() => setView('history')} />
            <NavButton active={view === 'admin'} icon={<Settings size={15} />} label="系统" onClick={() => setView('admin')} />
            </div>
          </nav>

          <div className="hidden shrink-0 items-center gap-2 lg:flex">
            <span className="inline-flex items-center gap-1.5 rounded-full border border-emerald-200 bg-emerald-50 px-3 py-1.5 text-xs font-medium text-emerald-700">
              <CheckCircle2 size={13} /> Mock 验收通过
            </span>
            <span className="rounded-full border border-slate-200 bg-white px-3 py-1.5 text-xs text-slate-500">v2 Workbench</span>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-[1760px] px-4 py-5 lg:px-5">
        <div className={view === 'admin' ? 'hidden' : ''}>
          <CreatorStudio view={creatorView} />
        </div>
        <div className={view === 'admin' ? '' : 'hidden'}>
          <AdminDashboard />
        </div>
      </main>
    </div>
  );
}

function NavButton(props: { active: boolean; icon: ReactNode; label: string; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={props.onClick}
      className={`inline-flex h-9 items-center gap-2 rounded-lg px-3 text-sm font-medium transition ${
        props.active ? 'bg-white text-slate-950 shadow-sm ring-1 ring-slate-200/70' : 'text-slate-500 hover:bg-white/70 hover:text-slate-900'
      }`}
    >
      {props.icon}
      {props.label}
    </button>
  );
}

export default App;
