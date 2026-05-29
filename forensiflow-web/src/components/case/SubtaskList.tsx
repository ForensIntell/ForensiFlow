import { CheckCircle, CircleNotch, Circle, WarningCircle } from "@phosphor-icons/react";
import { api } from "../../lib/api";
import { usePollingData } from "../../lib/hooks";

const statusIcon = {
  done: <CheckCircle size={15} weight="fill" className="text-success shrink-0" />,
  active: <CircleNotch size={15} className="text-accent animate-spin shrink-0" />,
  pending: <Circle size={15} className="text-text-dim shrink-0" />,
  error: <WarningCircle size={15} weight="fill" className="text-danger shrink-0" />,
};

const statusBg = {
  done: "bg-success-soft/40",
  active: "bg-accent-glow border-accent/20",
  pending: "",
  error: "bg-danger-soft/40",
};

export function SubtaskList() {
  const { data, loading, error, refresh } = usePollingData(() => api.workspaceState(false), 3000, []);
  const runtimeTasks = data?.subtasks ?? [];
  const latestJob = data?.latestJob;
  const title = data?.subtaskSource === "quick" ? "快速任务" : "规划子任务";

  return (
    <div className="flex flex-col gap-1">
      <div className="mb-1 flex items-center justify-between gap-2">
        <h3 className="text-[11px] font-medium uppercase tracking-widest text-text-dim">{title}</h3>
        <button onClick={refresh} className="text-[10px] text-accent hover:text-accent-hover">刷新</button>
      </div>
      {loading && <p className="rounded-lg border border-border-light bg-surface px-3 py-2 text-[11px] text-text-dim">正在读取后端任务状态...</p>}
      {error && <p className="rounded-lg border border-warning/30 bg-warning-soft px-3 py-2 text-[11px] text-warning">读取子任务失败：{error}</p>}
      {!loading && runtimeTasks.length === 0 && (
        <div className="rounded-lg border border-dashed border-border bg-surface/70 px-3 py-3 text-[11px] leading-relaxed text-text-dim">
          暂无规划层子任务。请先在“新建任务”生成规划，或在上方提交一个快速取证任务。
        </div>
      )}
      {runtimeTasks.map((t, i) => (
        <div
          key={t.id}
          className={`animate-fade-slide-up flex items-center gap-2.5 rounded-lg px-3 py-2 text-xs transition ${
            statusBg[t.status]
          } ${t.status === "active" ? "border border-accent/20" : "border border-transparent"}`}
          style={{ animationDelay: `${i * 60}ms` }}
        >
          {statusIcon[t.status]}
          <span className="font-mono-data text-[10px] text-text-dim">{String(t.sequence).padStart(2, "0")}</span>
          <span className={t.status === "active" ? "font-medium text-accent" : t.status === "done" ? "text-text-muted line-through" : "text-text-secondary"}>
            {t.label}
          </span>
          {t.schedulerUsed && (
            <span className="ml-auto rounded-md bg-bg px-1.5 py-0.5 text-[10px] text-text-dim">
              {t.schedulerUsed === "old" ? "复用" : "探索"}
            </span>
          )}
        </div>
      ))}
      {latestJob && (
        <p className="mt-1 font-mono-data text-[10px] text-text-dim">
          job {latestJob.id.slice(0, 10)} · {latestJob.status} · {data?.executionMode === "quick" ? "quick" : "planned"}
        </p>
      )}
    </div>
  );
}
