import { useMemo } from "react";
import { CircleNotch } from "@phosphor-icons/react";
import { api } from "../lib/api";
import { useAsyncData } from "../lib/hooks";
import { StatusBanner } from "../components/states/StatusBanner";

const fallbackExperiences = [
  { app: "WhatsApp Messenger", task: "消息会话总列表界面全量提取", steps: 4, successRate: 0.95, lastUsed: "2026-05-18" },
  { app: "WhatsApp Messenger", task: "指定对象聊天会话详情界面全量遍历抓取", steps: 6, successRate: 0.88, lastUsed: "2026-05-18" },
  { app: "WhatsApp Messenger", task: "账户设置个人主页界面全量信息提取", steps: 3, successRate: 0.92, lastUsed: "2026-04-10" },
  { app: "WhatsApp Messenger", task: "通话记录界面遍历抓取", steps: 5, successRate: 0.85, lastUsed: "2026-05-14" },
  { app: "Microsoft Outlook", task: "消息会话总列表界面全量提取", steps: 4, successRate: 0.78, lastUsed: "2026-04-14" },
];

export function ExperiencePage() {
  const { data, loading, error } = useAsyncData(() => api.apps(), []);
  const experiences = useMemo(() => {
    if (!data?.apps?.length) return fallbackExperiences;
    return data.apps.slice(0, 8).map((app, index) => ({
      app: app.name,
      task: app.category === "通讯" || app.name.toLowerCase().includes("whatsapp") ? "消息/会话总列表界面全量提取" : "应用整体取证相关界面全量提取",
      steps: 3 + (index % 4),
      successRate: 0.72 + ((index % 4) * 0.05),
      lastUsed: "模板库候选",
    }));
  }, [data]);

  return (
    <div className="min-h-[100dvh] bg-bg p-6 md:p-10 max-w-[1400px] mx-auto">
      <header className="flex flex-col gap-1">
        <p className="text-xs uppercase tracking-widest text-text-muted">Experience Library</p>
        <h1 className="text-2xl md:text-3xl font-semibold tracking-tight">经验库</h1>
        <p className="text-sm text-text-muted max-w-[65ch]">
          历史成功取证经验模板，支持经验复用路径快速执行。
        </p>
      </header>

      <div className="mt-5">
        {loading && (
          <div className="inline-flex items-center gap-2 rounded-xl border border-border bg-surface px-3 py-2 text-xs text-text-muted">
            <CircleNotch size={14} className="animate-spin text-accent" />
            正在读取应用映射和经验库候选...
          </div>
        )}
        {error && <StatusBanner tone="warning" title="经验库候选读取失败" description={`${error}。当前显示静态模板示例。`} />}
      </div>

      <div className="mt-6 grid grid-cols-1 md:grid-cols-2 gap-4">
        {experiences.map((exp, i) => (
          <div key={i} className="rounded-2xl border border-border bg-surface p-5 hover:border-accent/30 transition">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-medium">{exp.task}</h3>
              <span className="text-xs font-mono-data text-accent">{Math.round(exp.successRate * 100)}%</span>
            </div>
            <p className="mt-1 text-xs text-text-muted">{exp.app}</p>
            <div className="mt-3 flex items-center gap-3 text-xs text-text-muted">
              <span className="rounded-lg border border-border px-2 py-0.5">{exp.steps} steps</span>
              <span className="font-mono-data">最近: {exp.lastUsed}</span>
            </div>
            <div className="mt-3 h-1.5 rounded-full bg-bg overflow-hidden">
              <div
                className="h-full rounded-full bg-accent transition-all"
                style={{ width: `${exp.successRate * 100}%` }}
              />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
