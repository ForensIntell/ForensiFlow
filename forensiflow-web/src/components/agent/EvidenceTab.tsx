import { api, apiUrl } from "../../lib/api";
import { usePollingData } from "../../lib/hooks";

export function EvidenceTab() {
  const { data, loading, error } = usePollingData(() => api.evidence(), 5000, []);
  const evidence = data?.evidence?.slice(0, 8) ?? [];

  return (
    <ul className="flex flex-col gap-2.5 text-sm">
      {loading && <li className="rounded-xl border border-border-light bg-surface-raised p-4 text-xs text-text-dim">正在读取 records.json...</li>}
      {error && <li className="rounded-xl border border-warning/30 bg-warning-soft p-4 text-xs text-warning">证据接口不可用：{error}</li>}
      {!loading && !error && evidence.length === 0 && (
        <li className="rounded-xl border border-dashed border-border bg-surface-raised p-4 text-xs leading-relaxed text-text-dim">
          暂未发现取证任务输出的 records.json。
        </li>
      )}
      {evidence.map((ev, idx) => (
        <li
          key={ev.id}
          className="animate-fade-slide-up rounded-xl border border-border-light bg-surface-raised p-4 card-hover"
          style={{ animationDelay: `${idx * 80}ms` }}
        >
          <div className="flex items-center justify-between">
            <span className="rounded-md bg-info-soft px-2 py-0.5 text-info text-[11px] font-medium">
              {ev.evidenceType}
            </span>
            <span className="text-[11px] font-mono-data text-text-dim">{ev.timestamp}</span>
          </div>
          <p className="mt-2 text-text-secondary">{ev.summary}</p>
          <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-[11px]">
            <dt className="text-text-dim">文件</dt>
            <dd className="font-mono-data truncate">{ev.sourcePath || ev.page}</dd>
            <dt className="text-text-dim">记录数</dt>
            <dd className="font-mono-data">{ev.recordCount ?? "-"}</dd>
            <dt className="text-text-dim">哈希</dt>
            <dd className="font-mono-data text-accent">{ev.hash}</dd>
          </dl>
          {ev.downloadUrl && (
            <a
              href={apiUrl(ev.downloadUrl)}
              target="_blank"
              rel="noreferrer"
              className="mt-3 inline-flex rounded-lg border border-border px-2 py-1 text-[11px] text-text-muted hover:border-accent hover:text-accent transition"
            >
              打开 records.json
            </a>
          )}
        </li>
      ))}
    </ul>
  );
}
