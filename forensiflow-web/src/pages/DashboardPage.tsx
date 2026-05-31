import { DeviceMobile, ListChecks, Archive, ClockCounterClockwise, ArrowRight, CircleNotch, WarningCircle } from "@phosphor-icons/react";
import { Link } from "react-router-dom";
import { api, apiUrl } from "../lib/api";
import { useAsyncData } from "../lib/hooks";
import { StatusBanner } from "../components/states/StatusBanner";
import { EmptyState } from "../components/states/EmptyState";

const jobStatusLabel: Record<string, string> = {
  queued: "排队中",
  running: "执行中",
  succeeded: "已完成",
  failed: "失败",
};

export function DashboardPage() {
  const { data, loading, error, refresh } = useAsyncData(() => api.dashboard(), []);
  const metrics = [
    { label: "已连接设备", value: String(data?.metrics.connectedDevices ?? 0), icon: DeviceMobile, accent: "text-info", bg: "bg-info-soft" },
    { label: "后端作业", value: String(data?.metrics.runningJobs ?? 0), icon: ListChecks, accent: "text-success", bg: "bg-success-soft" },
    { label: "证据条目", value: String(data?.metrics.evidenceItems ?? 0), icon: Archive, accent: "text-warning", bg: "bg-warning-soft" },
    { label: "审计会话", value: String(data?.metrics.auditSessions ?? 0), icon: ClockCounterClockwise, accent: "text-accent", bg: "bg-accent-soft" },
  ];

  return (
    <div className="noise-bg min-h-[100dvh] bg-bg p-6 md:p-10 max-w-[1400px] mx-auto">
      <header className="flex flex-col gap-1">
        <p className="text-[11px] uppercase tracking-[0.15em] text-text-dim font-medium">System Overview</p>
        <h1 className="text-2xl md:text-[2rem] font-semibold tracking-tight leading-tight">
          ForensiFlow 控制台
        </h1>
        <p className="text-sm text-text-muted max-w-[65ch] mt-0.5">
          查看真实后端返回的设备连接状态、作业执行进度、证据采集结果与审计链完整性。
        </p>
      </header>

      <div className="mt-5">
        {loading && (
          <div className="inline-flex items-center gap-2 rounded-xl border border-border bg-surface px-3 py-2 text-xs text-text-muted">
            <CircleNotch size={14} className="animate-spin text-accent" />
            正在连接 ForensiFlow API...
          </div>
        )}
        {error && (
          <StatusBanner
            tone="danger"
            title="后端 API 暂不可用"
            description={`${error}。请先启动 tools/forensiflow_demo_api.py。`}
          />
        )}
      </div>

      <section className="mt-8 grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-3.5">
        {metrics.map((m, i) => (
          <div
            key={m.label}
            className="animate-fade-slide-up rounded-2xl border border-border-light bg-surface p-5 panel-shadow card-hover"
            style={{ animationDelay: `${i * 60}ms` }}
          >
            <div className={`w-fit rounded-xl ${m.bg} p-2.5 ${m.accent}`}>
              <m.icon size={20} weight="duotone" />
            </div>
            <p className="mt-3 text-[11px] text-text-dim uppercase tracking-wide">{m.label}</p>
            <p className="mt-1 text-[1.75rem] font-semibold tracking-tight font-mono-data leading-none">
              {m.value}
            </p>
          </div>
        ))}
      </section>

      {data?.devices && data.devices.length > 0 && (
        <section className="mt-8">
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-xs font-medium uppercase tracking-widest text-text-dim">设备状态</h2>
            <button onClick={refresh} className="text-xs text-accent hover:text-accent-hover transition">刷新</button>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            {data.devices.slice(0, 6).map((device) => (
              <div key={device.serial || device.model} className="rounded-2xl border border-border-light bg-surface p-4 panel-shadow">
                <div className="flex items-center justify-between">
                  <p className="text-sm font-medium truncate">{device.model}</p>
                  <span className={`rounded-full px-2 py-0.5 text-[11px] ${device.status === "connected" ? "bg-success-soft text-success" : "bg-warning-soft text-warning"}`}>
                    {device.status === "connected" ? "已连接" : "未连接"}
                  </span>
                </div>
                <p className="mt-1 font-mono-data text-[11px] text-text-dim truncate">{device.serial || device.adbState || "-"}</p>
                <div className="mt-3 flex items-center gap-3 text-[11px] text-text-muted">
                  <span>{device.taskCount} 任务</span>
                  <span>{device.evidenceCount} 证据</span>
                  <span className="ml-auto font-mono-data">{device.lastActiveAt}</span>
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      <section className="mt-8">
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-xs font-medium uppercase tracking-widest text-text-dim">最近证据</h2>
          <Link to="/evidence" className="inline-flex items-center gap-1 text-xs text-accent hover:text-accent-hover transition">
            查看证据库 <ArrowRight size={12} />
          </Link>
        </div>
        <div className="rounded-2xl border border-border-light bg-surface overflow-hidden panel-shadow">
          {!data?.recentEvidence?.length ? (
            <EmptyState title="暂无后端证据" description="后端未发现取证任务产出的 records.json。" />
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border text-[11px] text-text-dim text-left uppercase tracking-wide">
                  <th className="px-5 py-3 font-medium">类型</th>
                  <th className="px-5 py-3 font-medium">任务</th>
                  <th className="px-5 py-3 font-medium">应用</th>
                  <th className="px-5 py-3 font-medium">记录数</th>
                  <th className="px-5 py-3 font-medium">时间</th>
                </tr>
              </thead>
              <tbody>
                {data.recentEvidence.slice(0, 5).map((ev, i) => (
                  <tr
                    key={ev.id}
                    className="animate-fade-slide-up border-b border-border-light last:border-0 hover:bg-accent-glow/30 transition"
                    style={{ animationDelay: `${200 + i * 50}ms` }}
                  >
                    <td className="px-5 py-3">
                      <span className="rounded-md bg-info-soft px-1.5 py-0.5 text-xs text-info">{ev.evidenceType}</span>
                    </td>
                    <td className="px-5 py-3">
                      {ev.downloadUrl ? (
                        <a href={apiUrl(ev.downloadUrl)} target="_blank" rel="noreferrer" className="hover:text-accent transition font-medium">
                          {ev.summary}
                        </a>
                      ) : (
                        <span className="font-medium">{ev.summary}</span>
                      )}
                    </td>
                    <td className="px-5 py-3 text-text-muted">{ev.app}</td>
                    <td className="px-5 py-3 font-mono-data text-xs">{ev.recordCount ?? "-"}</td>
                    <td className="px-5 py-3 font-mono-data text-[11px] text-text-dim">{ev.timestamp}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </section>

      {data?.recentJobs && data.recentJobs.length > 0 && (
        <section className="mt-8">
          <h2 className="text-xs font-medium uppercase tracking-widest text-text-dim mb-3">后端执行作业</h2>
          <div className="rounded-2xl border border-border-light bg-surface overflow-hidden panel-shadow">
            {data.recentJobs.slice(0, 5).map((job) => (
              <div key={job.id} className="flex items-center gap-3 border-b border-border-light last:border-0 px-5 py-3 text-sm">
                {job.status === "running" ? <CircleNotch size={15} className="animate-spin text-accent" /> : job.status === "failed" ? <WarningCircle size={15} className="text-danger" /> : <ListChecks size={15} className="text-success" />}
                <span className="font-mono-data text-xs text-text-dim">{job.id.slice(0, 10)}</span>
                <span className="text-text-muted">{job.caseName || job.appName || "计划执行"}</span>
                <span className="ml-auto rounded-md bg-bg px-2 py-0.5 text-xs">{jobStatusLabel[job.status] || job.status}</span>
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
