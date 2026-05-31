import { useState } from "react";
import type { AuditSession } from "../types/stream";
import { api } from "../lib/api";
import { useAsyncData } from "../lib/hooks";
import { StatusBanner } from "../components/states/StatusBanner";
import {
  FolderOpen,
  DeviceMobile,
  Circle,
  CheckCircle,
  CircleNotch,
  CaretRight,
  CaretDown,
  Clock,
} from "@phosphor-icons/react";

const statusIcon = {
  completed: <CheckCircle size={14} weight="fill" className="text-success" />,
  running: <CircleNotch size={14} className="text-accent animate-spin" />,
  failed: <Circle size={14} weight="fill" className="text-danger" />,
};
const statusLabel = { completed: "已完成", running: "执行中", failed: "失败" };

function AuditTimeline({ session }: { session: AuditSession }) {
  return (
    <div className="relative ml-4 mt-3 mb-1">
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
              {s.pageSnapshot && (
                <span className="mt-1 inline-block rounded bg-bg px-1.5 py-0.5 text-[10px] text-text-dim font-mono-data">
                  {s.pageSnapshot}
                </span>
              )}
              {s.modelOutput && (
                <pre className="mt-1 rounded bg-bg px-2 py-1 text-[10px] font-mono-data text-text-secondary overflow-x-auto">
                  {s.modelOutput}
                </pre>
              )}
              {s.result && (
                <p className="mt-1 text-[11px] text-success">{s.result}</p>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export function AuditPage() {
  const { data, loading, error, refresh } = useAsyncData(() => api.audit(), []);
  const [expandedCase, setExpandedCase] = useState<string | null>(null);
  const [expandedDevice, setExpandedDevice] = useState<string | null>(null);
  const sessionsSource = data?.sessions ?? [];

  // Group by caseId
  const grouped = new Map<string, AuditSession[]>();
  for (const s of sessionsSource) {
    if (!grouped.has(s.caseId)) grouped.set(s.caseId, []);
    grouped.get(s.caseId)!.push(s);
  }

  const toggleCase = (caseId: string) => {
    setExpandedCase(expandedCase === caseId ? null : caseId);
    setExpandedDevice(null);
  };

  const toggleDevice = (key: string) => {
    setExpandedDevice(expandedDevice === key ? null : key);
  };

  return (
    <div className="noise-bg min-h-[100dvh] bg-bg p-6 md:p-10 max-w-[1100px] mx-auto">
      <header className="flex flex-col gap-1 mb-6">
        <p className="text-[11px] uppercase tracking-[0.15em] text-text-dim font-medium">Audit Replay</p>
        <h1 className="text-2xl md:text-[2rem] font-semibold tracking-tight">审计回放</h1>
        <p className="text-sm text-text-muted max-w-[65ch] mt-0.5">
          按案件和设备分类查看取证审计记录，确保每一步可追溯、可复核。
        </p>
      </header>

      <div className="mb-5">
        {loading && (
          <div className="inline-flex items-center gap-2 rounded-xl border border-border bg-surface px-3 py-2 text-xs text-text-muted">
            <CircleNotch size={14} className="animate-spin text-accent" />
            正在读取审计链与运行事件...
          </div>
        )}
        {error && <StatusBanner tone="danger" title="审计接口读取失败" description={error} />}
        {!loading && !error && !data?.sessions?.length && (
          <StatusBanner tone="warning" title="暂无后端审计记录" description="未发现 evidence_chain.jsonl 或 events.jsonl。" />
        )}
        {!loading && !error && Boolean(data?.sessions?.length) && (
          <div className="flex items-center justify-between">
            <StatusBanner tone="success" title="已接入后端审计数据" description={`读取到 ${data?.sessions.length ?? 0} 个审计/运行会话。`} />
            <button onClick={refresh} className="ml-3 rounded-xl border border-border bg-surface px-3 py-2 text-xs text-text-muted hover:border-border-hover transition">
              刷新
            </button>
          </div>
        )}
      </div>

      <div className="flex flex-col gap-3">
        {Array.from(grouped.entries()).map(([caseId, sessions]) => {
          const caseName = sessions[0].caseName;
          const caseOpen = expandedCase === caseId;

          return (
            <div key={caseId} className="rounded-2xl border border-border-light bg-surface panel-shadow overflow-hidden">
              {/* Case level */}
              <button
                onClick={() => toggleCase(caseId)}
                className="w-full flex items-center gap-3 px-5 py-3.5 hover:bg-accent-glow/30 transition text-left"
              >
                {caseOpen ? <CaretDown size={14} className="text-accent" /> : <CaretRight size={14} className="text-text-dim" />}
                <FolderOpen size={16} className="text-accent" />
                <div className="flex-1 min-w-0">
                  <span className="text-sm font-medium">{caseName}</span>
                  <span className="ml-2 font-mono-data text-[11px] text-text-dim">{caseId}</span>
                </div>
                <span className="text-[11px] text-text-dim">{sessions.length} 台设备</span>
              </button>

              {/* Device level */}
              {caseOpen && (
                <div className="border-t border-border-light">
                  {sessions.map((session) => {
                    const deviceKey = `${caseId}:${session.deviceSerial}`;
                    const deviceOpen = expandedDevice === deviceKey;

                    return (
                      <div key={deviceKey} className="border-b border-border-light last:border-b-0">
                        <button
                          onClick={() => toggleDevice(deviceKey)}
                          className="w-full flex items-center gap-3 px-5 py-3 pl-12 hover:bg-accent-glow/20 transition text-left"
                        >
                          {deviceOpen ? <CaretDown size={12} className="text-accent" /> : <CaretRight size={12} className="text-text-dim" />}
                          <DeviceMobile size={14} className="text-text-muted" />
                          <div className="flex-1 min-w-0 flex items-center gap-2">
                            <span className="text-xs font-medium">{session.deviceModel}</span>
                            <span className="font-mono-data text-[10px] text-text-dim">{session.deviceSerial}</span>
                          </div>
                          <div className="flex items-center gap-3">
                            {statusIcon[session.status]}
                            <span className="text-[11px] text-text-dim">{statusLabel[session.status]}</span>
                            <span className="flex items-center gap-1 text-[10px] text-text-dim font-mono-data">
                              <Clock size={10} /> {session.startedAt}
                            </span>
                            <span className="text-[10px] text-text-dim">{session.steps.length} 步</span>
                          </div>
                        </button>

                        {/* Timeline */}
                        {deviceOpen && <AuditTimeline session={session} />}
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          );
        })}

        {grouped.size === 0 && (
          <div className="flex flex-col items-center justify-center py-20 text-text-dim">
            <Clock size={48} weight="thin" />
            <p className="mt-3 text-sm">暂无审计记录</p>
          </div>
        )}
      </div>
    </div>
  );
}
