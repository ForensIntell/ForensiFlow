import React from "react";
import { useState } from "react";
import { Link } from "react-router-dom";
import {
  Plus,
  MagnifyingGlass,
  FunnelSimple,
  FolderOpen,
  Clock,
  DeviceMobile,
  Tag,
  Circle,
  CircleNotch,
} from "@phosphor-icons/react";
import { mockCases, caseTypes } from "../lib/mock-data";
import type { CaseItem, DeviceInCase } from "../types/stream";
import { api } from "../lib/api";
import { useAsyncData } from "../lib/hooks";
import { StatusBanner } from "../components/states/StatusBanner";

const statusConfig: Record<string, { label: string; color: string }> = {
  active: { label: "进行中", color: "bg-accent-soft text-accent" },
  closed: { label: "已结案", color: "bg-success-soft text-success" },
  pending: { label: "待启动", color: "bg-warning-soft text-warning" },
};

const deviceStatusIcon: Record<string, React.ReactElement> = {
  connected: <Circle size={7} weight="fill" className="text-success" />,
  processing: <CircleNotch size={10} className="text-accent animate-spin" />,
  disconnected: <Circle size={7} weight="fill" className="text-text-dim" />,
};
const deviceStatusLabel: Record<string, string> = {
  connected: "已连接", processing: "执行中", disconnected: "未连接",
};

function DeviceRow({ d }: { d: DeviceInCase }) {
  return (
    <div className="flex items-center gap-2 text-xs py-1.5">
      {deviceStatusIcon[d.status]}
      <span className="font-medium">{d.model}</span>
      <span className="font-mono-data text-[10px] text-text-dim">{d.serial}</span>
      <span className="text-text-dim">{deviceStatusLabel[d.status]}</span>
      <span className="ml-auto font-mono-data text-[10px] text-text-dim">{d.evidenceCount} 证据</span>
    </div>
  );
}

function CaseCard({ case: c, onClick }: { case: CaseItem; onClick: () => void }) {
  const st = statusConfig[c.status];
  const totalEvidence = c.devices.reduce((s, d) => s + d.evidenceCount, 0);
  const totalTasks = c.devices.reduce((s, d) => s + d.taskCount, 0);

  return (
    <div
      onClick={onClick}
      className="animate-fade-slide-up rounded-2xl border border-border-light bg-surface p-5 card-hover cursor-pointer group"
    >
      <div className="flex items-start justify-between">
        <div className="flex items-center gap-2">
          <div className="flex items-center justify-center w-7 h-7 rounded-lg bg-accent-soft text-accent group-hover:bg-accent group-hover:text-white transition">
            <FolderOpen size={14} />
          </div>
          <span className="font-mono-data text-[11px] text-text-dim">{c.id}</span>
        </div>
        <span className={`inline-block rounded-full px-2 py-0.5 text-[11px] font-medium ${st.color}`}>
          {st.label}
        </span>
      </div>

      <h3 className="mt-3 text-sm font-medium leading-snug line-clamp-2 group-hover:text-accent transition">
        {c.name}
      </h3>

      <div className="mt-2 flex items-center gap-1.5 flex-wrap">
        <span className="inline-flex items-center gap-1 rounded-md bg-bg px-1.5 py-0.5 text-[11px] text-text-muted">
          <Tag size={10} /> {c.caseType}
        </span>
        <span className="inline-flex items-center gap-1 rounded-md bg-bg px-1.5 py-0.5 text-[11px] text-text-muted">
          <DeviceMobile size={10} /> {c.devices.length} 台设备
        </span>
      </div>

      <p className="mt-2.5 text-xs text-text-muted leading-relaxed line-clamp-2">{c.description}</p>

      {/* Devices */}
      <div className="mt-3 pt-3 border-t border-border-light">
        {c.devices.slice(0, 3).map((d) => <DeviceRow key={d.serial} d={d} />)}
        {c.devices.length > 3 && (
          <p className="text-[10px] text-text-dim mt-1">+{c.devices.length - 3} 台设备</p>
        )}
      </div>

      <div className="mt-3 flex items-center justify-between text-[11px] text-text-dim">
        <span>{totalTasks} 任务 / {totalEvidence} 证据</span>
        <span className="flex items-center gap-1"><Clock size={10} /> {c.updatedAt}</span>
      </div>
    </div>
  );
}

export function CasesPage() {
  const { data: devicesData, loading, error, refresh } = useAsyncData(() => api.devices(), []);
  const cases = mockCases.map((item, index) => {
    if (index !== 0 || !devicesData?.devices?.length) return item;
    return {
      ...item,
      devices: devicesData.devices.map((device) => ({
        serial: device.serial || "-",
        model: device.model,
        status: device.status,
        taskCount: device.taskCount,
        evidenceCount: device.evidenceCount,
        lastActiveAt: device.lastActiveAt,
      })),
      updatedAt: devicesData.devices[0]?.lastActiveAt || item.updatedAt,
    };
  });
  const [search, setSearch] = useState("");
  const [filterType, setFilterType] = useState("");
  const [filterStatus, setFilterStatus] = useState("");
  const [selectedCase, setSelectedCase] = useState<CaseItem | null>(null);

  const filtered = cases.filter((c) => {
    if (search && !c.name.includes(search) && !c.id.includes(search) && !c.description.includes(search)) return false;
    if (filterType && c.caseType !== filterType) return false;
    if (filterStatus && c.status !== filterStatus) return false;
    return true;
  });

  return (
    <div className="noise-bg min-h-[100dvh] bg-bg p-6 md:p-10 max-w-[1400px] mx-auto">
      <header className="flex items-start justify-between gap-4">
        <div className="flex flex-col gap-1">
          <p className="text-[11px] uppercase tracking-[0.15em] text-text-dim font-medium">Case Management</p>
          <h1 className="text-2xl md:text-[2rem] font-semibold tracking-tight">案件管理</h1>
          <p className="text-sm text-text-muted max-w-[65ch] mt-0.5">创建、查看和管理所有取证案件，每台设备独立执行。</p>
        </div>
        <Link
          to="/task/new"
          className="inline-flex items-center gap-1.5 rounded-xl bg-accent px-4 py-2.5 text-sm text-white hover:bg-accent-hover transition btn-press panel-shadow"
        >
          <Plus size={16} weight="bold" /> 新建取证任务
        </Link>
      </header>

      <div className="mt-5">
        {loading && (
          <div className="inline-flex items-center gap-2 rounded-xl border border-border bg-surface px-3 py-2 text-xs text-text-muted">
            <CircleNotch size={14} className="animate-spin text-accent" />
            正在读取后端设备状态...
          </div>
        )}
        {error && (
          <StatusBanner
            tone="warning"
            title="设备状态读取失败，当前显示静态案件数据"
            description={error}
          />
        )}
        {!loading && !error && (
          <StatusBanner
            tone="success"
            title="已接入后端设备状态"
            description={`读取到 ${devicesData?.devices.length ?? 0} 台设备/历史设备。`}
          />
        )}
      </div>

      <div className="mt-6 flex flex-wrap items-center gap-3">
        <div className="relative flex-1 min-w-[240px] max-w-md">
          <MagnifyingGlass size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-text-dim" />
          <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="搜索案件名称、编号..."
            className="w-full rounded-xl border border-border bg-surface py-2 pl-9 pr-3 text-sm outline-none focus:border-accent focus:ring-2 focus:ring-accent-soft transition" />
        </div>
        <select value={filterType} onChange={(e) => setFilterType(e.target.value)}
          className="rounded-xl border border-border bg-surface px-3 py-2 text-xs text-text-muted outline-none focus:border-accent">
          <option value="">全部类型</option>
          {caseTypes.map((t) => <option key={t} value={t}>{t}</option>)}
        </select>
        <select value={filterStatus} onChange={(e) => setFilterStatus(e.target.value)}
          className="rounded-xl border border-border bg-surface px-3 py-2 text-xs text-text-muted outline-none focus:border-accent">
          <option value="">全部状态</option>
          <option value="active">进行中</option><option value="pending">待启动</option><option value="closed">已结案</option>
        </select>
        <span className="text-[11px] text-text-dim flex items-center gap-1"><FunnelSimple size={13} /> {filtered.length} / {cases.length}</span>
        <button onClick={refresh} className="rounded-xl border border-border bg-surface px-3 py-2 text-xs text-text-muted hover:border-border-hover transition">
          刷新设备
        </button>
      </div>

      <div className="mt-6 grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
        {filtered.map((c, i) => (
          <div key={c.id} style={{ animationDelay: `${i * 60}ms` }}>
            <CaseCard case={c} onClick={() => setSelectedCase(c)} />
          </div>
        ))}
        {filtered.length === 0 && (
          <div className="col-span-full flex flex-col items-center justify-center py-20 text-text-dim">
            <FolderOpen size={48} weight="thin" /><p className="mt-3 text-sm">没有匹配的案件</p>
          </div>
        )}
      </div>

      {/* Detail modal */}
      {selectedCase && (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
          <div className="absolute inset-0 bg-black/30 backdrop-blur-sm" onClick={() => setSelectedCase(null)} />
          <div className="relative w-full max-w-2xl max-h-[80vh] overflow-y-auto rounded-2xl border border-border bg-surface p-6 panel-shadow-lg">
            <div className="flex items-start justify-between">
              <div>
                <span className="font-mono-data text-[11px] text-text-dim">{selectedCase.id}</span>
                <h2 className="mt-1 text-lg font-semibold tracking-tight">{selectedCase.name}</h2>
              </div>
              <button onClick={() => setSelectedCase(null)} className="text-text-dim hover:text-text text-xl leading-none">&times;</button>
            </div>

            <div className="mt-5 grid grid-cols-2 gap-4 text-sm">
              <div className="flex flex-col gap-1"><span className="text-[11px] text-text-dim">案件类型</span><span className="flex items-center gap-1"><Tag size={13} /> {selectedCase.caseType}</span></div>
              <div className="flex flex-col gap-1"><span className="text-[11px] text-text-dim">状态</span><span className={`w-fit rounded-full px-2 py-0.5 text-[11px] font-medium ${statusConfig[selectedCase.status].color}`}>{statusConfig[selectedCase.status].label}</span></div>
              <div className="flex flex-col gap-1"><span className="text-[11px] text-text-dim">创建时间</span><span className="font-mono-data text-xs">{selectedCase.createdAt}</span></div>
              <div className="flex flex-col gap-1"><span className="text-[11px] text-text-dim">更新时间</span><span className="font-mono-data text-xs">{selectedCase.updatedAt}</span></div>
            </div>

            <div className="mt-4">
              <span className="text-[11px] text-text-dim">案件描述</span>
              <p className="mt-1 text-sm text-text-secondary leading-relaxed">{selectedCase.description}</p>
            </div>

            {/* Device list */}
            <div className="mt-5">
              <span className="text-[11px] text-text-dim uppercase tracking-wide">关联设备 ({selectedCase.devices.length})</span>
              <div className="mt-2 flex flex-col gap-2">
                {selectedCase.devices.map((d) => (
                  <div key={d.serial} className="flex items-center gap-3 rounded-xl border border-border-light bg-bg px-4 py-3">
                    {deviceStatusIcon[d.status]}
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-medium">{d.model}</span>
                        <span className="font-mono-data text-[10px] text-text-dim">{d.serial}</span>
                      </div>
                      <div className="flex items-center gap-3 mt-0.5 text-[11px] text-text-dim">
                        <span>{deviceStatusLabel[d.status]}</span>
                        <span>{d.taskCount} 任务</span>
                        <span>{d.evidenceCount} 证据</span>
                        <span>最近: {d.lastActiveAt}</span>
                      </div>
                    </div>
                    <Link
                      to="/workspace"
                      className="rounded-lg bg-accent px-3 py-1.5 text-xs text-white hover:bg-accent-hover transition btn-press"
                    >
                      进入工作台
                    </Link>
                  </div>
                ))}
              </div>
            </div>

            <div className="mt-6 flex items-center gap-3">
              <Link to="/audit" className="rounded-xl border border-border px-4 py-2 text-sm text-text-muted hover:bg-bg transition">
                查看审计记录
              </Link>
              <button className="rounded-xl border border-border px-4 py-2 text-sm text-text-muted hover:bg-bg transition">
                导出报告
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
