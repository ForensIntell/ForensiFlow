import { Link } from "react-router-dom";
import { Plus, DeviceMobile, CircleNotch, Circle } from "@phosphor-icons/react";
import { api } from "../lib/api";
import { useAsyncData } from "../lib/hooks";
import { StatusBanner } from "../components/states/StatusBanner";
import { EmptyState } from "../components/states/EmptyState";

const deviceStatusLabel: Record<string, string> = {
  connected: "已连接",
  processing: "执行中",
  disconnected: "未连接",
};

export function CasesPage() {
  const { data, loading, error, refresh } = useAsyncData(() => api.devices(), []);
  const devices = data?.devices ?? [];

  return (
    <div className="noise-bg min-h-[100dvh] bg-bg p-6 md:p-10 max-w-[1100px] mx-auto">
      <header className="flex items-start justify-between gap-4">
        <div className="flex flex-col gap-1">
          <p className="text-[11px] uppercase tracking-[0.15em] text-text-dim font-medium">Case Management</p>
          <h1 className="text-2xl md:text-[2rem] font-semibold tracking-tight">案件管理</h1>
          <p className="text-sm text-text-muted max-w-[65ch] mt-0.5">
            当前后端暂未提供案件列表、详情、搜索、编辑、删除或案件级报告接口；本页不再展示静态案件数据。
          </p>
        </div>
        <Link
          to="/task/new"
          className="inline-flex items-center gap-1.5 rounded-xl bg-accent px-4 py-2.5 text-sm text-white hover:bg-accent-hover transition btn-press panel-shadow"
        >
          <Plus size={16} weight="bold" /> 新建取证任务
        </Link>
      </header>

      <div className="mt-5 flex flex-col gap-3">
        <StatusBanner
          tone="warning"
          title="案件管理后端接口未接入"
          description="案件 CRUD、案件搜索筛选、案件详情弹窗、案件报告导出均已隐藏；后端补齐接口后再恢复这些入口。"
        />
        {loading && (
          <div className="inline-flex w-fit items-center gap-2 rounded-xl border border-border bg-surface px-3 py-2 text-xs text-text-muted">
            <CircleNotch size={14} className="animate-spin text-accent" />
            正在读取后端设备状态...
          </div>
        )}
        {error && <StatusBanner tone="danger" title="设备状态读取失败" description={error} />}
      </div>

      <section className="mt-8">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-xs font-medium uppercase tracking-widest text-text-dim">后端可用设备状态</h2>
          <button onClick={refresh} className="rounded-xl border border-border bg-surface px-3 py-2 text-xs text-text-muted hover:border-border-hover transition">
            刷新设备
          </button>
        </div>

        <div className="rounded-2xl border border-border-light bg-surface overflow-hidden panel-shadow">
          {!loading && devices.length === 0 ? (
            <EmptyState title="暂无设备数据" description="后端未返回连接设备或历史设备。" />
          ) : (
            <div className="divide-y divide-border-light">
              {devices.map((device) => (
                <div key={device.serial || device.model} className="flex items-center gap-4 px-5 py-4">
                  <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-accent-soft text-accent">
                    <DeviceMobile size={18} />
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <p className="truncate text-sm font-medium">{device.model}</p>
                      <span className="font-mono-data text-[10px] text-text-dim">{device.serial || "-"}</span>
                    </div>
                    <div className="mt-1 flex flex-wrap items-center gap-3 text-[11px] text-text-dim">
                      <span className="inline-flex items-center gap-1">
                        <Circle size={7} weight="fill" className={device.status === "connected" ? "text-success" : "text-text-dim"} />
                        {deviceStatusLabel[device.status] || device.status}
                      </span>
                      <span>{device.taskCount} 任务</span>
                      <span>{device.evidenceCount} 证据</span>
                      <span className="font-mono-data">最近: {device.lastActiveAt}</span>
                    </div>
                  </div>
                  <Link to="/workspace" className="rounded-lg bg-accent px-3 py-1.5 text-xs text-white hover:bg-accent-hover transition btn-press">
                    进入工作台
                  </Link>
                </div>
              ))}
            </div>
          )}
        </div>
      </section>
    </div>
  );
}
