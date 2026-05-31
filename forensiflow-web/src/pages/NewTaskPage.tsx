import { useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  ArrowRight,
  ArrowLeft,
  Sparkle,
  CheckCircle,
  Circle,
  CircleNotch,
  Play,
  WarningCircle,
  DeviceMobile,
} from "@phosphor-icons/react";
import { caseTypes } from "../lib/case-options";
import type { Subtask } from "../types/stream";
import { api, type ForensicPlan } from "../lib/api";
import { StatusBanner } from "../components/states/StatusBanner";
import { useAsyncData } from "../lib/hooks";

type Step = "input" | "planning" | "confirm";

function generateSubtasks(plan: ForensicPlan): Subtask[] {
  const tasks: Subtask[] = [];
  let id = 1;
  for (const appPlan of plan.forensic_plan) {
    for (const task of appPlan.tasks) {
      tasks.push({ id: id++, label: `[L${task.task_level}] ${task.task_description}`, status: "pending" });
    }
  }
  return tasks;
}

export function NewTaskPage() {
  const navigate = useNavigate();
  const { data: devicesData, loading: devicesLoading, error: devicesError } = useAsyncData(() => api.devices(), []);
  const knownDevices = devicesData?.devices ?? [];
  const [step, setStep] = useState<Step>("input");
  const [form, setForm] = useState({
    caseName: "",
    caseType: "",
    devices: [""],
    caseBackground: "",
    forensicGoals: "",
  });
  const [subtasks, setSubtasks] = useState<Subtask[]>([]);
  const [planning, setPlanning] = useState(false);
  const [plan, setPlan] = useState<ForensicPlan | null>(null);
  const [planSource, setPlanSource] = useState<"llm" | "fallback" | "">("");
  const [warnings, setWarnings] = useState<string[]>([]);
  const [error, setError] = useState("");
  const [starting, setStarting] = useState(false);
  const [startedJob, setStartedJob] = useState("");
  const selectedDeviceSerial = form.devices.find(Boolean) || "";

  const handlePlan = async () => {
    setStep("planning");
    setPlanning(true);
    setError("");
    setWarnings([]);
    setPlan(null);
    setPlanSource("");
    try {
      const response = await api.createPlan({
        case_name: form.caseName,
        case_type: form.caseType,
        case_background: form.caseBackground,
        forensic_goals: form.forensicGoals,
        device_serial: selectedDeviceSerial,
        allow_fallback: true,
      });
      setPlan(response.plan);
      setPlanSource(response.source);
      setWarnings(response.warnings ?? []);
      setSubtasks(generateSubtasks(response.plan));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setSubtasks([]);
    } finally {
      setPlanning(false);
    }
  };

  const handleConfirm = () => {
    setStep("confirm");
  };

  const handleStart = async () => {
    if (!plan) return;
    if (!selectedDeviceSerial) {
      setError("需要设备序列号才能提交真实执行任务。");
      return;
    }
    setStarting(true);
    setError("");
    try {
      const response = await api.startTask({
        plan,
        device_serial: selectedDeviceSerial,
        app_name: plan.forensic_plan[0]?.app_name || "",
        threshold: 0.75,
        execution_mode: "planned",
        case_name: form.caseName,
      });
      setStartedJob(response.job.id);
      setTimeout(() => navigate("/workspace"), 600);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setStarting(false);
    }
  };

  const canProceedInput = Boolean(form.caseName && form.caseType && form.forensicGoals);

  return (
    <div className="min-h-[100dvh] bg-bg p-6 md:p-10 max-w-[1000px] mx-auto">
      <header className="flex flex-col gap-1 mb-8">
        <p className="text-xs uppercase tracking-widest text-text-muted">New Forensic Task</p>
        <h1 className="text-2xl md:text-3xl font-semibold tracking-tight">新建取证任务</h1>
        <p className="text-sm text-text-muted">
          输入案件背景和取证目标，系统将自动规划取证子任务。
        </p>
      </header>

      {/* Step indicator */}
      <div className="flex items-center gap-3 mb-8">
        {(["input", "planning", "confirm"] as Step[]).map((s, i) => {
          const labels = ["输入信息", "任务规划", "确认执行"];
          const active = step === s;
          const done = (step === "planning" && s === "input") || (step === "confirm" && s !== "confirm");
          return (
            <div key={s} className="flex items-center gap-3">
              <div className={`flex items-center gap-2 text-xs ${active ? "text-accent" : done ? "text-success" : "text-text-dim"}`}>
                <span className={`flex h-6 w-6 items-center justify-center rounded-full border text-xs font-mono-data ${
                  active ? "border-accent bg-accent-soft" : done ? "border-success bg-success-soft" : "border-border"
                }`}>
                  {done ? <CheckCircle size={14} /> : i + 1}
                </span>
                <span>{labels[i]}</span>
              </div>
              {i < 2 && <div className={`w-8 h-px ${done ? "bg-success" : "bg-border"}`} />}
            </div>
          );
        })}
      </div>

      {/* Step 1: Input */}
      {step === "input" && (
        <div className="flex flex-col gap-5">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="flex flex-col gap-1.5">
              <label className="text-xs text-text-muted">案件名称 *</label>
              <input
                value={form.caseName}
                onChange={(e) => setForm({ ...form, caseName: e.target.value })}
                placeholder="如：涉嫌诈骗案 - WhatsApp 证据采集"
                className="rounded-xl border border-border bg-surface px-3 py-2.5 text-sm outline-none focus:border-accent focus:ring-2 focus:ring-accent-soft"
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <label className="text-xs text-text-muted">案件类型 *</label>
              <select
                value={form.caseType}
                onChange={(e) => setForm({ ...form, caseType: e.target.value })}
                className="rounded-xl border border-border bg-surface px-3 py-2.5 text-sm outline-none focus:border-accent focus:ring-2 focus:ring-accent-soft"
              >
                <option value="">请选择案件类型</option>
                {caseTypes.map((t) => <option key={t} value={t}>{t}</option>)}
              </select>
            </div>
          </div>

          <div className="flex flex-col gap-1.5">
            <label className="text-xs text-text-muted">关联设备（每行一台设备序列号）</label>
            <textarea
              value={form.devices.join("\n")}
              onChange={(e) => setForm({ ...form, devices: e.target.value.split("\n").filter(Boolean) })}
              placeholder={"emulator-5554\nAQMLUT3510003748\n（每行一台，可选）"}
              rows={2}
              className="rounded-xl border border-border bg-surface px-3 py-2.5 text-sm outline-none focus:border-accent focus:ring-2 focus:ring-accent-soft resize-none font-mono-data"
            />
            {devicesLoading && <p className="text-[11px] text-text-dim">正在读取后端设备列表...</p>}
            {devicesError && <p className="text-[11px] text-warning">设备列表读取失败：{devicesError}</p>}
            {knownDevices.length > 0 && (
              <div className="flex flex-wrap gap-2 pt-1">
                {knownDevices.map((device) => (
                  <button
                    key={device.serial || device.model}
                    type="button"
                    onClick={() => setForm({ ...form, devices: [device.serial].filter(Boolean) })}
                    disabled={!device.serial}
                    className="inline-flex items-center gap-1.5 rounded-lg border border-border bg-surface px-2.5 py-1.5 text-[11px] text-text-muted hover:border-accent hover:text-accent disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    <DeviceMobile size={12} />
                    <span className="font-mono-data">{device.serial || "无序列号"}</span>
                    <span>{device.status === "connected" ? "已连接" : "历史设备"}</span>
                  </button>
                ))}
              </div>
            )}
          </div>

          <div className="flex flex-col gap-1.5">
            <label className="text-xs text-text-muted">案件背景 *</label>
            <textarea
              value={form.caseBackground}
              onChange={(e) => setForm({ ...form, caseBackground: e.target.value })}
              placeholder={"描述案件基本情况，包括：\n- 案件类型和概况\n- 涉案人员信息（如有）\n- 涉及的应用或平台\n- 时间范围\n- 其他相关线索"}
              rows={5}
              className="rounded-xl border border-border bg-surface px-3 py-2.5 text-sm outline-none focus:border-accent focus:ring-2 focus:ring-accent-soft resize-none leading-relaxed"
            />
          </div>

          <div className="flex flex-col gap-1.5">
            <label className="text-xs text-text-muted">取证目标 *</label>
            <textarea
              value={form.forensicGoals}
              onChange={(e) => setForm({ ...form, forensicGoals: e.target.value })}
              placeholder={"描述需要提取的具体证据，每行一个目标，例如：\n- 提取 Chrome 浏览历史记录\n- 提取 Gmail 收件箱邮件列表\n- 提取 Google Maps 最近地点信息\n- 获取联系人列表"}
              rows={4}
              className="rounded-xl border border-border bg-surface px-3 py-2.5 text-sm outline-none focus:border-accent focus:ring-2 focus:ring-accent-soft resize-none leading-relaxed"
            />
          </div>

          <div className="flex justify-end">
            <button
              onClick={handlePlan}
              disabled={!canProceedInput}
              className="inline-flex items-center gap-2 rounded-xl bg-accent px-5 py-2.5 text-sm text-white hover:bg-accent-hover transition active:scale-[.98] disabled:opacity-40 disabled:cursor-not-allowed"
            >
              <Sparkle size={16} />
              生成取证规划
              <ArrowRight size={14} />
            </button>
          </div>
        </div>
      )}

      {/* Step 2: Planning */}
      {step === "planning" && (
        <div className="flex flex-col gap-6">
          {error && <StatusBanner tone="danger" title="规划接口调用失败" description={error} />}
          {planSource === "fallback" && (
            <StatusBanner
              tone="warning"
              title="当前使用本地安全预览规划"
              description={warnings[0] || "后端 LLM 不可用，当前规划来自后端本地 fallback。"}
            />
          )}
          {planSource === "llm" && <StatusBanner tone="success" title="已调用后端 LLM 规划能力" description="规划结果来自 ForensicPlanner。" />}

          {/* Case analysis */}
          <div className="rounded-2xl border border-border bg-surface p-5">
            <h3 className="text-xs font-medium uppercase tracking-widest text-text-muted mb-2">案件分析摘要</h3>
            {planning ? (
              <div className="flex items-center gap-2 text-sm text-text-muted">
                <CircleNotch size={16} className="animate-spin text-accent" />
                AI 正在分析案件背景和取证目标，生成取证规划...
              </div>
            ) : (
              <p className="text-sm text-text leading-relaxed">{plan?.case_analysis_summary || "暂无规划结果。"}</p>
            )}
          </div>

          {/* Generated plan */}
          {!planning && plan?.forensic_plan.map((appPlan) => (
            <div key={`${appPlan.app_name}-${appPlan.package_name}`} className="rounded-2xl border border-border bg-surface p-5">
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-sm font-medium">{appPlan.app_name}</h3>
                <span className="font-mono-data text-xs text-text-dim">{appPlan.package_name}</span>
              </div>

              <div className="flex flex-col gap-2">
                {appPlan.tasks.map((task, i) => (
                  <div key={i} className="flex items-start gap-3 rounded-xl bg-bg px-4 py-3">
                    <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full border border-border text-xs font-mono-data mt-0.5">
                      {i + 1}
                    </span>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="rounded-md bg-accent-soft px-1.5 py-0.5 text-xs text-accent font-mono-data">
                          L{task.task_level}
                        </span>
                        <span className="rounded-md bg-bg border border-border px-1.5 py-0.5 text-xs text-text-muted">
                          {task.task_type}
                        </span>
                        {task.target_objects.length > 0 && (
                          <span className="rounded-md bg-warning-soft px-1.5 py-0.5 text-xs text-warning">
                            对象: {task.target_objects.join(", ")}
                          </span>
                        )}
                      </div>
                      <p className="mt-1 text-sm">{task.task_description}</p>
                      {task.constraint && (
                        <p className="mt-1 text-xs text-text-dim">约束: {task.constraint}</p>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ))}

          {/* Subtask preview */}
          {!planning && (
            <div className="rounded-2xl border border-border bg-surface p-5">
              <h3 className="text-xs font-medium uppercase tracking-widest text-text-muted mb-3">
                拆分后的子任务列表（共 {subtasks.length} 项）
              </h3>
              <div className="flex flex-col gap-1.5">
                {subtasks.map((t) => (
                  <div key={t.id} className="flex items-center gap-3 text-sm py-1">
                    <Circle size={14} className="text-text-dim shrink-0" />
                    <span className="font-mono-data text-xs text-text-dim">{String(t.id).padStart(2, "0")}</span>
                    <span>{t.label}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Actions */}
          <div className="flex items-center justify-between">
            <button
              onClick={() => setStep("input")}
              className="inline-flex items-center gap-1.5 rounded-xl border border-border px-4 py-2.5 text-sm text-text-muted hover:bg-bg transition"
            >
              <ArrowLeft size={14} />
              返回修改
            </button>
            {!planning && (
              <button
                onClick={handleConfirm}
                disabled={!plan}
                className="inline-flex items-center gap-2 rounded-xl bg-accent px-5 py-2.5 text-sm text-white hover:bg-accent-hover transition active:scale-[.98] disabled:opacity-50 disabled:cursor-not-allowed"
              >
                确认规划
                <ArrowRight size={14} />
              </button>
            )}
          </div>
        </div>
      )}

      {/* Step 3: Confirm */}
      {step === "confirm" && (
        <div className="flex flex-col gap-6">
            <div className="rounded-2xl border border-success/40 bg-success-soft/30 p-5">
              <div className="flex items-center gap-2 text-success mb-2">
                <CheckCircle size={20} />
                <span className="text-sm font-medium">取证规划已就绪</span>
              </div>
              <p className="text-sm text-text-muted">
                系统已根据案件背景和取证目标生成了 {subtasks.length} 个子任务。
                点击"开始执行"将进入取证工作台，系统将按照规划逐步执行任务。
              </p>
            </div>

          {planSource === "fallback" && (
            <StatusBanner
              tone="warning"
              title="启动将调用真实后端执行入口"
              description="当前规划为后端本地 fallback。连接真实设备和 LLM 后建议重新生成规划。"
            />
          )}
          {startedJob && <StatusBanner tone="success" title="任务已提交" description={`后端作业 ID: ${startedJob}`} />}
          {!selectedDeviceSerial && (
            <StatusBanner tone="warning" title="缺少设备序列号" description="后端执行入口需要设备序列号；请返回输入信息选择或填写设备。" />
          )}
          {error && (
            <div className="flex items-start gap-2 rounded-xl border border-danger/30 bg-danger-soft p-3 text-danger">
              <WarningCircle size={16} weight="fill" className="mt-0.5" />
              <p className="text-sm">{error}</p>
            </div>
          )}

          <div className="rounded-2xl border border-border bg-surface p-5">
            <h3 className="text-xs font-medium uppercase tracking-widest text-text-muted mb-3">任务概览</h3>
            <dl className="grid grid-cols-2 gap-x-6 gap-y-3 text-sm">
              <dt className="text-text-muted">案件名称</dt>
              <dd>{form.caseName}</dd>
              <dt className="text-text-muted">案件类型</dt>
              <dd>{form.caseType}</dd>
              <dt className="text-text-muted">子任务数</dt>
              <dd className="font-mono-data">{subtasks.length}</dd>
              <dt className="text-text-muted">涉及应用</dt>
              <dd>{plan?.forensic_plan.map(p => p.app_name).join(", ") || "-"}</dd>
              <dt className="text-text-muted">设备 ({form.devices.length})</dt>
              <dd className="font-mono-data">{selectedDeviceSerial || "待填写"}</dd>
            </dl>
          </div>

          <div className="flex items-center justify-between">
            <button
              onClick={() => setStep("planning")}
              className="inline-flex items-center gap-1.5 rounded-xl border border-border px-4 py-2.5 text-sm text-text-muted hover:bg-bg transition"
            >
              <ArrowLeft size={14} />
              返回规划
            </button>
            <button
              onClick={handleStart}
              disabled={!plan || starting || !selectedDeviceSerial}
              className="inline-flex items-center gap-2 rounded-xl bg-accent px-6 py-2.5 text-sm text-white hover:bg-accent-hover transition active:scale-[.98] disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {starting ? <CircleNotch size={16} className="animate-spin" /> : <Play size={16} weight="fill" />}
              {starting ? "提交中..." : "开始执行"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
