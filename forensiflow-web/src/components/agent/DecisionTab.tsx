import { Target, CrosshairSimple, Lightning, Gauge } from "@phosphor-icons/react";
import { api } from "../../lib/api";
import { usePollingData } from "../../lib/hooks";

export function DecisionTab() {
  const { data, loading, error } = usePollingData(() => api.workspaceState(false), 2500, []);
  const latestJob = data?.latestJob;
  const current = data?.currentAction;
  const statusLabel = latestJob ? `${latestJob.status} / ${latestJob.id.slice(0, 10)}` : "等待任务";
  const modeLabel = data?.subtaskSource === "quick" ? "快速任务直达调度器" : data?.subtaskSource === "planned" ? "规划层子任务执行" : "未提交任务";
  const schedulerLabel = current?.schedulerLabel || (current?.schedulerUsed === "old" ? "复用执行器" : current?.schedulerUsed === "new" ? "探索 Agent" : "待选择");
  const score = typeof current?.similarityScore === "number" ? Math.max(0, Math.min(1, current.similarityScore)) : null;

  return (
    <div className="flex flex-col gap-3 text-sm">
      {/* Planning mode */}
      <div className="rounded-xl border border-border-light bg-surface-raised p-4">
        <div className="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-widest text-text-dim mb-2">
          <Lightning size={12} className="text-accent" />
          规划模式
        </div>
        <div className="flex items-center gap-3">
          <span className="text-sm font-medium">{modeLabel}</span>
          <span className="rounded-md bg-accent-soft px-2 py-0.5 text-[11px] text-accent font-medium">
            {statusLabel}
          </span>
        </div>
        <p className="mt-1 text-xs text-text-dim">
          {loading ? "正在读取后端运行状态..." : error ? `状态接口异常：${error}` : `调度器：${schedulerLabel}`}
        </p>
      </div>

      {/* Current action */}
      <div className="rounded-xl border border-accent/20 bg-accent-glow p-4">
        <div className="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-widest text-accent mb-2">
          <Target size={12} />
          当前动作
        </div>
        <p className="text-sm font-medium">
          {current?.action || "等待后端执行动作"}
        </p>
        {current?.target && <p className="mt-1 break-words text-xs leading-relaxed text-text-secondary">{current.target}</p>}
        <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-xs">
          <dt className="text-text-dim flex items-center gap-1"><CrosshairSimple size={11} /> 操作来源</dt>
          <dd>{current?.source || "-"}</dd>
          <dt className="text-text-dim flex items-center gap-1"><CrosshairSimple size={11} /> 操作类型</dt>
          <dd className="font-mono-data">{current?.operation || "-"}</dd>
          <dt className="text-text-dim flex items-center gap-1"><Gauge size={11} /> 匹配得分</dt>
          <dd>
            <span className="font-mono-data text-accent font-semibold">{score === null ? "-" : score.toFixed(3)}</span>
            <span className="ml-2 inline-block w-16 h-1.5 rounded-full bg-border overflow-hidden align-middle">
              <span className="block h-full rounded-full bg-accent" style={{ width: `${score === null ? 0 : score * 100}%` }} />
            </span>
          </dd>
          <dt className="text-text-dim flex items-center gap-1"><Gauge size={11} /> 当前任务</dt>
          <dd>{current?.taskName || "无运行任务"}</dd>
        </dl>
      </div>

      {/* Page summary */}
      <div className="rounded-xl border border-border-light bg-surface-raised p-4">
        <div className="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-widest text-text-dim mb-2">
          执行摘要
        </div>
        <p className="text-xs text-text-secondary leading-relaxed">
          {data?.planSummary ||
            "工作台显示连接手机、规划层子任务或快速任务状态，以及后端执行器从日志和 Agent 事件中解析出的当前手机操作。"}
        </p>
      </div>
    </div>
  );
}
