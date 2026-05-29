import { api } from "../../lib/api";
import { usePollingData } from "../../lib/hooks";

interface Props {
  score: number;
  mode: string;
}

export function RouteScoreBadge({ score, mode }: Props) {
  const { data } = usePollingData(() => api.workspaceState(false), 5000, []);
  const currentScore = typeof data?.currentAction.similarityScore === "number" ? data.currentAction.similarityScore : score;
  const currentMode = data?.currentAction.schedulerLabel || mode;
  const pct = Math.round(Math.max(0, Math.min(1, currentScore)) * 100);
  return (
    <div className="rounded-xl border border-accent/20 bg-accent-glow p-3">
      <div className="flex items-center justify-between">
        <span className="text-[11px] text-text-dim uppercase tracking-wide">执行路径</span>
        <span className="font-mono-data text-sm font-semibold text-accent">{pct}%</span>
      </div>
      <p className="mt-1 text-xs font-medium text-accent">{currentMode}</p>
      <div className="mt-2 h-1.5 rounded-full bg-accent-soft overflow-hidden">
        <div
          className="h-full rounded-full bg-accent transition-all duration-700"
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}
