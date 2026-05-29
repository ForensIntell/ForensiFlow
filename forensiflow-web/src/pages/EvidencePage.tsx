import { FunnelSimple, Download, MagnifyingGlass, CircleNotch } from "@phosphor-icons/react";
import { useMemo, useState } from "react";
import { api, apiUrl } from "../lib/api";
import { useAsyncData } from "../lib/hooks";
import { StatusBanner } from "../components/states/StatusBanner";
import { EmptyState } from "../components/states/EmptyState";

export function EvidencePage() {
  const { data, loading, error, refresh } = useAsyncData(() => api.evidence(), []);
  const [search, setSearch] = useState("");
  const [exporting, setExporting] = useState(false);
  const evidence = useMemo(() => data?.evidence ?? [], [data?.evidence]);
  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return evidence;
    return evidence.filter((ev) =>
      [ev.evidenceType, ev.summary, ev.app, ev.page, ev.hash, ev.deviceSerial, ev.sourcePath, ev.runDir]
        .join(" ")
        .toLowerCase()
        .includes(q)
    );
  }, [evidence, search]);

  const handleExport = async () => {
    setExporting(true);
    try {
      const response = await api.createReport({ title: "ForensiFlow 证据报告" });
      window.open(apiUrl(response.downloadUrl), "_blank", "noopener,noreferrer");
    } finally {
      setExporting(false);
    }
  };

  return (
    <div className="min-h-[100dvh] bg-bg p-6 md:p-10 max-w-[1400px] mx-auto">
      <header className="flex flex-col gap-1">
        <p className="text-xs uppercase tracking-widest text-text-muted">Evidence Library</p>
        <h1 className="text-2xl md:text-3xl font-semibold tracking-tight">证据库</h1>
        <p className="text-sm text-text-muted max-w-[65ch]">
          展示取证任务产出的 records.json 文件位置，点击条目直接打开原始结构化记录。
        </p>
      </header>

      <div className="mt-5">
        {loading && (
          <div className="inline-flex items-center gap-2 rounded-xl border border-border bg-surface px-3 py-2 text-xs text-text-muted">
            <CircleNotch size={14} className="animate-spin text-accent" />
            正在读取 records.json 证据...
          </div>
        )}
        {error && <StatusBanner tone="danger" title="证据接口读取失败" description={error} />}
        {!loading && evidence.length === 0 && !error && (
          <StatusBanner tone="warning" title="暂无后端证据记录" description="未发现取证任务产出的 records.json。" />
        )}
      </div>

      <div className="mt-6 flex flex-wrap items-center gap-3">
        <div className="relative flex-1 min-w-[240px] max-w-md">
          <MagnifyingGlass size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-text-dim" />
          <input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="搜索证据..."
            className="w-full rounded-xl border border-border bg-surface py-2 pl-9 pr-3 text-sm outline-none focus:border-accent focus:ring-2 focus:ring-accent-soft"
          />
        </div>
        <button onClick={refresh} className="inline-flex items-center gap-1.5 rounded-xl border border-border bg-surface px-3 py-2 text-xs text-text-muted hover:border-border-hover transition">
          <FunnelSimple size={14} /> 刷新
        </button>
        <button
          onClick={handleExport}
          disabled={exporting}
          className="inline-flex items-center gap-1.5 rounded-xl bg-accent px-3 py-2 text-xs text-white hover:bg-accent-hover transition disabled:opacity-50"
        >
          {exporting ? <CircleNotch size={14} className="animate-spin" /> : <Download size={14} />} 导出报告
        </button>
      </div>

      <div className="mt-6 rounded-2xl border border-border bg-surface overflow-hidden">
        {filtered.length === 0 ? (
          <EmptyState title="暂无匹配证据" description="调整搜索条件，或先从工作台启动一次取证任务。" />
        ) : (
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border text-xs text-text-muted text-left">
              <th className="px-5 py-3 font-medium">类型</th>
              <th className="px-5 py-3 font-medium">任务名称</th>
              <th className="px-5 py-3 font-medium">应用</th>
              <th className="px-5 py-3 font-medium">文件位置</th>
              <th className="px-5 py-3 font-medium">记录数</th>
              <th className="px-5 py-3 font-medium">哈希</th>
              <th className="px-5 py-3 font-medium">时间</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((ev) => (
              <tr
                key={ev.id}
                onClick={() => {
                  if (ev.downloadUrl) window.open(apiUrl(ev.downloadUrl), "_blank", "noopener,noreferrer");
                }}
                className="border-b border-border last:border-0 hover:bg-bg/50 transition cursor-pointer"
              >
                <td className="px-5 py-3">
                  <span className="inline-block rounded-lg bg-info-soft text-info text-xs px-2 py-0.5">{ev.evidenceType}</span>
                </td>
                <td className="px-5 py-3">{ev.summary}</td>
                <td className="px-5 py-3 text-text-muted">{ev.app}</td>
                <td className="max-w-[360px] truncate px-5 py-3 font-mono-data text-xs text-text-muted">{ev.sourcePath || ev.page}</td>
                <td className="px-5 py-3 font-mono-data text-xs">{ev.recordCount ?? "-"}</td>
                <td className="px-5 py-3 font-mono-data text-xs text-accent">{ev.hash}</td>
                <td className="px-5 py-3 font-mono-data text-xs text-text-muted">{ev.timestamp}</td>
              </tr>
            ))}
          </tbody>
        </table>
        )}
      </div>
    </div>
  );
}
