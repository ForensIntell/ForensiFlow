import { Package, TreeStructure, CrosshairSimple, GitBranch } from "@phosphor-icons/react";
import type { WorkspaceStateResponse } from "../../lib/api";

export function PageSummaryBar({ state }: { state: WorkspaceStateResponse | null }) {
  const device = state?.selectedDevice;
  const screenshot = state?.liveScreenshot;
  const action = state?.currentAction;
  const packageName = state?.subtasks?.[0]?.packageName || (action?.taskName?.toLowerCase().includes("whatsapp") ? "com.whatsapp" : "device");

  return (
    <div className="flex items-center justify-between gap-4 border-b border-border bg-surface/60 backdrop-blur-sm px-4 py-2 text-[11px] text-text-muted">
      <div className="flex items-center gap-2.5">
        <span className="inline-flex items-center gap-1 rounded-md bg-accent-soft px-1.5 py-0.5 text-accent font-medium">
          <Package size={11} />
          {packageName}
        </span>
        <span className="flex items-center gap-1">
          <TreeStructure size={11} className="text-text-dim" />
          {device?.model || "等待设备"}
        </span>
        <span className="flex items-center gap-1 text-text-dim">
          <CrosshairSimple size={11} />
          {device?.status === "connected" ? "ADB connected" : device?.adbState || "ADB standby"}
        </span>
        <span className="flex items-center gap-1 text-accent font-medium">
          <CrosshairSimple size={11} />
          {action?.action || "等待当前动作"}
        </span>
      </div>

      <div className="flex items-center gap-2">
        <span className="inline-flex items-center gap-1 rounded-md bg-success-soft px-1.5 py-0.5 text-success font-medium">
          <GitBranch size={11} />
          {screenshot?.ok ? "live capture" : "no live frame"}
        </span>
        <span className="rounded-md bg-bg px-1.5 py-0.5 text-text-dim">
          {state?.subtaskSource === "quick" ? "quick task" : state?.subtaskSource === "planned" ? "planned tasks" : "standby"}
        </span>
      </div>
    </div>
  );
}
