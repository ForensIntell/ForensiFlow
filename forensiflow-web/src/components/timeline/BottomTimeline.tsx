import { api } from "../../lib/api";
import { usePollingData } from "../../lib/hooks";

export function BottomTimeline() {
  const { data } = usePollingData(() => api.workspaceState(false), 4000, []);
  const latestJob = data?.latestJob;
  const subtasks = data?.subtasks ?? [];
  const steps = subtasks.length > 0
    ? subtasks.map((task) => task.taskDescription || task.label)
    : ["等待任务提交", "调度器选择", "执行手机动作", "证据落盘", "审计链"];
  const activeCount = subtasks.length > 0
    ? Math.max(1, subtasks.filter((task) => task.status === "done" || task.status === "active").length)
    : latestJob?.status === "succeeded" ? steps.length : latestJob?.status === "running" ? 3 : 1;

  return (
    <div className="flex items-center gap-0 overflow-x-auto px-4 py-2.5 scrollbar-thin">
      {steps.map((step, i) => {
        const active = i < activeCount;
        return (
          <div key={step} className="flex items-center shrink-0">
            <div
              className={`flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] transition ${
                active
                  ? "bg-accent-soft text-accent font-medium"
                  : "text-text-dim"
              }`}
            >
              <span className="font-mono-data text-[10px] opacity-60">{String(i + 1).padStart(2, "0")}</span>
              <span>{step}</span>
              {active && i === activeCount - 1 && latestJob?.status === "running" && (
                <span className="relative flex h-1.5 w-1.5">
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-accent opacity-50" />
                  <span className="relative inline-flex rounded-full h-1.5 w-1.5 bg-accent" />
                </span>
              )}
            </div>
            {i < steps.length - 1 && (
              <div className={`w-6 h-px mx-0.5 ${active ? "bg-accent/30" : "bg-border"}`} />
            )}
          </div>
        );
      })}
    </div>
  );
}
