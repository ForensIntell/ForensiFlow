import { api } from "../../lib/api";
import { useAsyncData } from "../../lib/hooks";

export default function AppList() {
  const { data, loading, error, refresh } = useAsyncData(() => api.apps(), []);
  const apps = data?.apps ?? [];

  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-center justify-between mb-1">
        <span className="text-xs font-semibold uppercase tracking-[0.1em] text-text-muted">
          Installed Apps
        </span>
        <button onClick={refresh} className="text-[10px] text-accent hover:text-accent-hover">
          刷新
        </button>
      </div>
      {loading && <p className="text-[11px] text-text-dim">正在读取后端应用映射...</p>}
      {error && <p className="text-[11px] text-warning">读取应用映射失败：{error}</p>}
      {!loading && !error && apps.length === 0 && (
        <p className="rounded-lg border border-dashed border-border bg-surface/70 px-3 py-3 text-[11px] leading-relaxed text-text-dim">
          后端未返回应用映射，请先采集设备应用列表。
        </p>
      )}

      <ul className="flex flex-col gap-0.5">
        {apps.slice(0, 8).map((app, index) => (
          <li
            key={app.package ?? index}
            className="flex items-center gap-2.5 rounded-lg px-2.5 py-2 hover:bg-surface transition-colors"
          >
            <div className="flex flex-col flex-1 min-w-0">
              <span className="text-sm font-medium text-text truncate">
                {app.name}
              </span>
              <span className="text-[11px] font-mono text-text-muted truncate">
                {app.package}
              </span>
            </div>

            {app.category && (
              <span className="shrink-0 inline-flex items-center rounded-md bg-bg border border-border px-1.5 py-0.5 text-[10px] font-medium text-text-muted uppercase tracking-wide">
                {app.category}
              </span>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
