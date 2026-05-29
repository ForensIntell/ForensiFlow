import { api } from "../../lib/api";
import { usePollingData } from "../../lib/hooks";

export function AuditTab() {
  const { data, loading, error } = usePollingData(() => api.audit(), 5000, []);
  // Show the first running/completed session's steps as the "current" audit
  const sessions = data?.sessions ?? [];
  const session = sessions.find(s => s.status === "running") || sessions[0];
  if (!session) return <p className="text-xs text-text-dim">暂无审计记录</p>;

  return (
      <div className="relative">
        {loading && <p className="mb-3 rounded-xl border border-border-light bg-surface-raised p-3 text-xs text-text-dim">正在读取后端审计事件...</p>}
      {error && <p className="mb-3 rounded-xl border border-warning/30 bg-warning-soft p-3 text-xs text-warning">审计接口不可用：{error}</p>}
      <div className="absolute left-[11px] top-0 bottom-0 w-px bg-border" />
      <div className="flex flex-col gap-0.5">
        {session.steps.map((s) => (
          <div key={s.step} className="relative flex gap-3 pl-0 group/step">
            <div className="relative z-10 flex h-6 w-6 shrink-0 items-center justify-center rounded-full border border-border bg-surface text-[10px] font-mono-data group-hover/step:border-accent group-hover/step:text-accent transition">
              {s.step}
            </div>
            <div className="flex-1 rounded-lg border border-transparent group-hover/step:border-border-light group-hover/step:bg-surface-raised px-3 py-2 transition">
              <div className="flex items-center justify-between">
                <p className="text-xs">{s.action}</p>
                <span className="text-[10px] font-mono-data text-text-dim">{s.timestamp}</span>
              </div>
              {s.result && <p className="mt-1 text-[11px] text-success">{s.result}</p>}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
