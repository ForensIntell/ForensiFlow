import { useState } from "react";
import { CircleNotch } from "@phosphor-icons/react";
import { api } from "../lib/api";
import { useAsyncData } from "../lib/hooks";
import { StatusBanner } from "../components/states/StatusBanner";

function SettingGroup({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-2xl border border-border bg-surface p-6">
      <h2 className="text-sm font-medium mb-4">{title}</h2>
      <div className="flex flex-col gap-4">{children}</div>
    </section>
  );
}

function Field({ label, defaultValue, helper }: { label: string; defaultValue: string; helper?: string }) {
  return (
    <div className="flex flex-col gap-1.5">
      <label className="text-xs text-text-muted">{label}</label>
      <input
        defaultValue={defaultValue}
        className="rounded-xl border border-border bg-bg px-3 py-2 text-sm outline-none focus:border-accent focus:ring-2 focus:ring-accent-soft"
      />
      {helper && <p className="text-xs text-text-dim">{helper}</p>}
    </div>
  );
}

function Toggle({ label, defaultChecked }: { label: string; defaultChecked?: boolean }) {
  const [on, setOn] = useState(!!defaultChecked);
  return (
    <label className="flex items-center justify-between cursor-pointer">
      <span className="text-sm">{label}</span>
      <button
        type="button"
        role="switch"
        aria-checked={on}
        onClick={() => setOn(!on)}
        className={`relative h-6 w-11 rounded-full transition-colors ${on ? "bg-accent" : "bg-border"}`}
      >
        <span
          className={`absolute top-0.5 left-0.5 h-5 w-5 rounded-full bg-white shadow transition-transform ${on ? "translate-x-5" : "translate-x-0"}`}
        />
      </button>
    </label>
  );
}

export function SettingsPage() {
  const { data, loading, error, refresh } = useAsyncData(() => api.health(), []);

  return (
    <div className="min-h-[100dvh] bg-bg p-6 md:p-10 max-w-[900px] mx-auto">
      <header className="flex flex-col gap-1 mb-8">
        <p className="text-xs uppercase tracking-widest text-text-muted">Settings</p>
        <h1 className="text-2xl md:text-3xl font-semibold tracking-tight">设置</h1>
      </header>

      <div className="mb-6">
        {loading && (
          <div className="inline-flex items-center gap-2 rounded-xl border border-border bg-surface px-3 py-2 text-xs text-text-muted">
            <CircleNotch size={14} className="animate-spin text-accent" />
            正在检查后端配置...
          </div>
        )}
        {error && <StatusBanner tone="danger" title="后端健康检查失败" description={error} />}
        {data && (
          <StatusBanner
            tone={data.adb.ok && data.llmConfigured ? "success" : "warning"}
            title="后端健康检查"
            description={`ADB: ${data.adb.ok ? `${data.adb.devices.length} 台设备` : "不可用"}；LLM: ${data.llmConfigured ? "已配置" : "未配置"}；数据目录: ${data.dataDirExists ? "存在" : "缺失"}`}
          />
        )}
      </div>

      <div className="flex flex-col gap-6">
        <SettingGroup title="模型配置">
          <Field label="LLM API Base" defaultValue="从 .env / .env.mimo 加载" />
          <Field label="LLM Model" defaultValue="从 .env / .env.mimo 加载" />
          <Field label="API Key" defaultValue={data?.llmConfigured ? "已配置" : "未配置"} helper="后端不会向前端返回密钥原文" />
        </SettingGroup>

        <SettingGroup title="设备连接">
          <Field label="ADB 路径" defaultValue="/usr/bin/adb" />
          <Field label="设备序列号" defaultValue={data?.adb.devices.map((item) => `${item.serial}:${item.state}`).join(", ") || "未检测到"} />
          <button onClick={refresh} className="w-fit rounded-xl border border-border px-3 py-2 text-xs text-text-muted hover:bg-bg transition">重新检查</button>
        </SettingGroup>

        <SettingGroup title="取证配置">
          <Field label="截图保存目录" defaultValue="./data/screenshots" />
          <Field label="证据导出路径" defaultValue="./data/evidence_export" />
          <Field label="BGE 模型路径" defaultValue="./external/models/bge-large-zh-v1.5" />
          <Toggle label="审计链开启" defaultChecked />
          <Toggle label="自动经验沉淀" defaultChecked />
          <Toggle label="Demo 日志模式" />
        </SettingGroup>
      </div>
    </div>
  );
}
