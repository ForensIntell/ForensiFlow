import { Books, CircleNotch } from "@phosphor-icons/react";
import { api } from "../lib/api";
import { useAsyncData } from "../lib/hooks";
import { StatusBanner } from "../components/states/StatusBanner";

export function ExperiencePage() {
  const { data, loading, error, refresh } = useAsyncData(() => api.health(), []);

  return (
    <div className="min-h-[100dvh] bg-bg p-6 md:p-10 max-w-[1000px] mx-auto">
      <header className="flex flex-col gap-1">
        <p className="text-xs uppercase tracking-widest text-text-muted">Experience Library</p>
        <h1 className="text-2xl md:text-3xl font-semibold tracking-tight">经验库</h1>
        <p className="text-sm text-text-muted max-w-[65ch]">
          Web 后端当前没有暴露 RAG 经验模板列表、模板详情、索引重建或复用统计接口，因此前端不再展示静态经验卡片。
        </p>
      </header>

      <div className="mt-5 flex flex-col gap-3">
        {loading && (
          <div className="inline-flex w-fit items-center gap-2 rounded-xl border border-border bg-surface px-3 py-2 text-xs text-text-muted">
            <CircleNotch size={14} className="animate-spin text-accent" />
            正在检查后端能力...
          </div>
        )}
        {error && <StatusBanner tone="danger" title="后端能力读取失败" description={error} />}
        {data && (
          <StatusBanner
            tone="warning"
            title="经验库接口暂未开放"
            description="当前后端 health 能力列表未包含 experience_templates / rag_template_stats / rebuild_index 等接口。"
          />
        )}
      </div>

      <section className="mt-8 rounded-2xl border border-border bg-surface p-6">
        <div className="flex items-start gap-4">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-accent-soft text-accent">
            <Books size={20} />
          </div>
          <div className="min-w-0">
            <h2 className="text-sm font-medium">后续需要后端补充的能力</h2>
            <p className="mt-2 text-sm leading-relaxed text-text-muted">
              建议新增经验模板列表、模板详情、模板启停、索引重建、复用命中统计和模板下载接口。
              接口补齐前，本页只保留能力说明，不提供可点击的假功能。
            </p>
            <button
              type="button"
              onClick={refresh}
              className="mt-4 rounded-xl border border-border px-3 py-2 text-xs text-text-muted hover:bg-bg transition"
            >
              重新检查后端能力
            </button>
          </div>
        </div>
      </section>
    </div>
  );
}
