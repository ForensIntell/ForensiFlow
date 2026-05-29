import { useState } from "react";
import { CircleNotch, Play } from "@phosphor-icons/react";
import { api } from "../../lib/api";

export default function TaskInput() {
  const [task, setTask] = useState("提取 WhatsApp 中与 kndxx 的聊天记录");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  const handleStart = async () => {
    setBusy(true);
    setMessage("");
    try {
      const response = await api.startQuickTask({
        task_description: task,
        app_name: "WhatsApp Messenger",
        package_name: "com.whatsapp",
        threshold: 0.75,
      });
      setMessage(`快速任务已直接提交调度器 ${response.job.id.slice(0, 10)}，系统会选择复用执行或探索 Agent。`);
    } catch (err) {
      setMessage(`提交失败：${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex flex-col gap-2.5">
      <label
        htmlFor="forensic-task"
        className="text-xs font-semibold uppercase tracking-[0.1em] text-text-muted"
      >
        取证任务
      </label>

      <textarea
        id="forensic-task"
        rows={3}
        value={task}
        onChange={(event) => setTask(event.target.value)}
        className="w-full resize-none rounded-xl border border-border bg-surface px-3.5 py-2.5 text-sm text-text leading-relaxed placeholder:text-text-muted/50 focus:outline-none focus:ring-2 focus:ring-accent/60 focus:border-accent transition-shadow"
      />

      <button
        onClick={handleStart}
        disabled={busy || !task.trim()}
        className="inline-flex items-center justify-center gap-1.5 rounded-xl bg-accent px-3 py-2 text-xs text-white hover:bg-accent-hover transition disabled:opacity-50 disabled:cursor-not-allowed"
      >
        {busy ? <CircleNotch size={14} className="animate-spin" /> : <Play size={14} weight="fill" />}
        {busy ? "提交中..." : "启动快速任务"}
      </button>
      {message && <p className={`text-[11px] leading-relaxed ${message.startsWith("提交失败") ? "text-danger" : "text-success"}`}>{message}</p>}
      <p className="text-[11px] leading-relaxed text-text-dim">
        快速取证不会调用案件规划层，只把当前单个任务交给后端调度器。
      </p>

      <div className="flex items-center gap-2">
        <span className="inline-flex items-center rounded-md bg-accent-soft px-2 py-0.5 text-[11px] font-semibold text-accent">
          Level 3
        </span>
        <span className="inline-flex items-center rounded-md bg-bg px-2 py-0.5 text-[11px] font-mono text-text-muted border border-border">
          targeted_object_extraction
        </span>
      </div>
    </div>
  );
}
