import { useState } from "react";
import { CircleNotch, Play } from "@phosphor-icons/react";
import { api } from "../../lib/api";
import { useAsyncData } from "../../lib/hooks";

export default function TaskInput() {
  const { data: appsData, loading: appsLoading, error: appsError } = useAsyncData(() => api.apps(), []);
  const { data: devicesData, loading: devicesLoading, error: devicesError } = useAsyncData(() => api.devices(), []);
  const apps = appsData?.apps ?? [];
  const devices = devicesData?.devices ?? [];
  const [task, setTask] = useState("");
  const [selectedPackage, setSelectedPackage] = useState("");
  const [manualAppName, setManualAppName] = useState("");
  const [manualPackageName, setManualPackageName] = useState("");
  const [selectedDeviceSerial, setSelectedDeviceSerial] = useState("");
  const [manualDeviceSerial, setManualDeviceSerial] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  const selectedApp = apps.find((app) => app.package === selectedPackage) ?? (!selectedPackage && apps[0] ? apps[0] : undefined);
  const selectedDevice =
    devices.find((device) => device.serial === selectedDeviceSerial) ??
    (!selectedDeviceSerial ? devices.find((device) => device.status === "connected") ?? devices[0] : undefined);
  const appName = selectedApp?.name || manualAppName.trim();
  const packageName = selectedApp?.package || manualPackageName.trim();
  const deviceSerial = manualDeviceSerial.trim() || selectedDevice?.serial || "";
  const canStart = Boolean(task.trim() && (appName || packageName) && deviceSerial);

  const handleStart = async () => {
    if (!canStart) return;
    setBusy(true);
    setMessage("");
    try {
      const response = await api.startQuickTask({
        task_description: task,
        app_name: appName,
        package_name: packageName,
        device_serial: deviceSerial,
        threshold: 0.75,
      });
      setMessage(`快速任务已提交调度器 ${response.job.id.slice(0, 10)}，后端会选择复用执行或探索 Agent。`);
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
        placeholder="输入单个取证任务，例如：提取 Chrome 浏览历史记录"
        className="w-full resize-none rounded-xl border border-border bg-surface px-3.5 py-2.5 text-sm text-text leading-relaxed placeholder:text-text-muted/50 focus:outline-none focus:ring-2 focus:ring-accent/60 focus:border-accent transition-shadow"
      />

      {apps.length > 0 ? (
        <select
          value={selectedPackage || selectedApp?.package || ""}
          onChange={(event) => setSelectedPackage(event.target.value)}
          className="rounded-xl border border-border bg-surface px-3 py-2 text-xs text-text-muted outline-none focus:border-accent"
        >
          {apps.map((app) => (
            <option key={app.package} value={app.package}>
              {app.name} ({app.package})
            </option>
          ))}
        </select>
      ) : (
        <div className="grid grid-cols-1 gap-2">
          <input
            value={manualAppName}
            onChange={(event) => setManualAppName(event.target.value)}
            placeholder="应用名称（后端应用映射为空时填写）"
            className="rounded-xl border border-border bg-surface px-3 py-2 text-xs outline-none focus:border-accent"
          />
          <input
            value={manualPackageName}
            onChange={(event) => setManualPackageName(event.target.value)}
            placeholder="包名，可选"
            className="rounded-xl border border-border bg-surface px-3 py-2 text-xs font-mono-data outline-none focus:border-accent"
          />
        </div>
      )}
      {appsLoading && <p className="text-[11px] text-text-dim">正在读取后端应用映射...</p>}
      {appsError && <p className="text-[11px] text-warning">应用映射读取失败，可手动填写应用名称：{appsError}</p>}

      {devices.length > 0 ? (
        <select
          value={selectedDeviceSerial || selectedDevice?.serial || ""}
          onChange={(event) => setSelectedDeviceSerial(event.target.value)}
          className="rounded-xl border border-border bg-surface px-3 py-2 text-xs text-text-muted outline-none focus:border-accent"
        >
          {devices.map((device) => (
            <option key={device.serial || device.model} value={device.serial}>
              {device.model} ({device.serial || "无序列号"}) - {device.status === "connected" ? "已连接" : "未连接"}
            </option>
          ))}
        </select>
      ) : (
        <p className="text-[11px] text-warning">后端未返回设备列表，请手动填写设备序列号。</p>
      )}
      <input
        value={manualDeviceSerial}
        onChange={(event) => setManualDeviceSerial(event.target.value)}
        placeholder="设备序列号（可手动覆盖）"
        className="rounded-xl border border-border bg-surface px-3 py-2 text-xs font-mono-data outline-none focus:border-accent"
      />
      {devicesLoading && <p className="text-[11px] text-text-dim">正在读取后端设备列表...</p>}
      {devicesError && <p className="text-[11px] text-warning">设备列表读取失败：{devicesError}</p>}
      {!deviceSerial && <p className="text-[11px] text-warning">需要设备序列号才能提交真实执行任务。</p>}

      <button
        onClick={handleStart}
        disabled={busy || !canStart}
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
