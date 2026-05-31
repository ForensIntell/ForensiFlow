import { useState } from "react";
import { ShieldCheck, WifiHigh, Export, Circle, CircleNotch } from "@phosphor-icons/react";
import { api, apiUrl } from "../../lib/api";
import { useAsyncData } from "../../lib/hooks";

export function AppTopbar() {
  const { data, loading, error } = useAsyncData(() => api.workspaceState(false), []);
  const [exporting, setExporting] = useState(false);
  const device = data?.selectedDevice ?? data?.devices?.find((item) => item.status === "connected") ?? data?.devices?.[0];
  const currentTask = data?.currentAction?.taskName || data?.latestJob?.caseName || data?.latestJob?.appName || "未提交任务";

  const handleExport = async () => {
    setExporting(true);
    try {
      const response = await api.createReport({ title: "ForensiFlow 工作台报告" });
      window.open(apiUrl(response.downloadUrl), "_blank", "noopener,noreferrer");
    } finally {
      setExporting(false);
    }
  };

  return (
    <header className="flex items-center justify-between h-13 border-b border-border bg-surface/80 backdrop-blur-sm px-5 sticky top-0 z-40">
      {/* Left: Logo + Title */}
      <div className="flex items-center gap-3">
        <div className="flex items-center justify-center w-8 h-8 rounded-lg bg-accent text-white">
          <ShieldCheck size={18} weight="bold" />
        </div>
        <div className="flex flex-col">
          <span className="text-sm font-semibold tracking-tight leading-none">ForensiFlow</span>
          <span className="text-[10px] text-text-dim tracking-wide uppercase">Forensic Workstation</span>
        </div>
      </div>

      {/* Center: breadcrumb-style context */}
      <div className="hidden md:flex items-center gap-2 text-xs text-text-muted">
        <span className="rounded-md bg-accent-soft px-2 py-0.5 text-accent font-medium">
          {data?.latestJob?.id ? data.latestJob.id.slice(0, 10) : "等待任务"}
        </span>
        <span className="text-text-dim">/</span>
        <span>{currentTask}</span>
      </div>

      {/* Right: Status + Actions */}
      <div className="flex items-center gap-3">
        <div className="flex items-center gap-1.5 text-xs text-text-muted">
          <span className="relative flex items-center gap-1">
            {loading ? <CircleNotch size={13} className="animate-spin text-accent" /> : <Circle size={7} weight="fill" className={device?.status === "connected" ? "text-success" : "text-warning"} />}
            <WifiHigh size={14} className={device?.status === "connected" ? "text-success" : "text-warning"} />
          </span>
          <span>{error ? "API 未连接" : device?.status === "connected" ? "已连接" : "未连接"}</span>
          {device?.serial && <span className="hidden lg:inline font-mono-data text-[10px] text-text-dim">{device.serial}</span>}
        </div>
        <div className="h-4 w-px bg-border" />
        <div className="flex items-center gap-1.5 text-xs text-text-muted">
          <ShieldCheck size={14} className="text-accent" />
          <span>审计: 开启</span>
        </div>
        <div className="h-4 w-px bg-border" />
        <button
          onClick={handleExport}
          disabled={exporting}
          className="inline-flex items-center gap-1.5 rounded-lg bg-accent/90 hover:bg-accent px-3 py-1.5 text-xs text-white transition btn-press disabled:opacity-50"
        >
          {exporting ? <CircleNotch size={13} className="animate-spin" /> : <Export size={13} />}
          {exporting ? "生成中" : "导出报告"}
        </button>
      </div>
    </header>
  );
}
