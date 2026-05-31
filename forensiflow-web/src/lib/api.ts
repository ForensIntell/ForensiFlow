import type { AuditSession, EvidenceItem } from "../types/stream";

const API_BASE = (
  import.meta.env.VITE_API_BASE_URL ??
  import.meta.env.VITE_FORENSIFLOW_API_BASE ??
  ""
).replace(/\/$/, "");

export interface ApiDevice {
  serial: string;
  model: string;
  status: "connected" | "disconnected" | "processing";
  adbState?: string;
  androidVersion?: string;
  manufacturer?: string;
  taskCount: number;
  evidenceCount: number;
  lastActiveAt: string;
}

export interface ApiAppInfo {
  name: string;
  package: string;
  category: string;
}

export interface HealthResponse {
  ok: boolean;
  adb: { ok: boolean; devices: Array<{ serial: string; state: string }>; error?: string };
  llmConfigured: boolean;
  dataDirExists: boolean;
  evidenceAvailable: boolean;
  capabilities: string[];
}

export interface DashboardResponse {
  devices: ApiDevice[];
  metrics: {
    connectedDevices: number;
    knownDevices: number;
    evidenceItems: number;
    auditSessions: number;
    runningJobs: number;
  };
  recentEvidence: EvidenceItem[];
  recentJobs: JobInfo[];
  auditSessions: AuditSession[];
  screenshots: ScreenshotItem[];
}

export interface ForensicTask {
  task_level: number;
  task_type: string;
  task_description: string;
  target_objects: string[];
  constraint: string;
}

export interface ForensicAppPlan {
  app_name: string;
  package_name: string;
  tasks: ForensicTask[];
}

export interface ForensicPlan {
  case_analysis_summary: string;
  forensic_plan: ForensicAppPlan[];
}

export interface PlanResponse {
  ok: boolean;
  source: "llm" | "fallback";
  warnings: string[];
  plan: ForensicPlan;
  planPath: string;
}

export interface JobInfo {
  id: string;
  status: "queued" | "running" | "succeeded" | "failed";
  createdAt: string;
  startedAt?: string;
  finishedAt?: string;
  returncode?: number;
  stdoutPath?: string;
  stderrPath?: string;
  planPath?: string;
  deviceSerial?: string;
  appName?: string;
  taskIndex?: number | null;
  executionMode?: "planned" | "quick";
  caseName?: string;
}

export interface JobDetailResponse {
  job: JobInfo;
  logs: { stdout: string; stderr: string };
}

export interface ScreenshotItem {
  path: string;
  url: string;
  name: string;
  mtime: string;
  runDir: string;
}

export interface LiveScreenshot {
  ok: boolean;
  serial: string;
  path?: string;
  url?: string;
  capturedAt?: string;
  error?: string;
}

export interface WorkspaceSubtask {
  id: string;
  sequence: number;
  appIndex: number;
  taskIndex: number;
  appName: string;
  packageName: string;
  taskLevel: number;
  taskType: string;
  taskDescription: string;
  label: string;
  targetObjects: string[];
  constraint: string;
  status: "pending" | "active" | "done" | "error";
  schedulerUsed?: "old" | "new" | "";
  similarityScore?: number | null;
  runDir?: string;
  error?: string;
}

export interface CurrentAction {
  status: string;
  action: string;
  operation: string;
  target: string;
  source: string;
  raw?: string;
  jobId: string;
  taskName: string;
  schedulerUsed?: "old" | "new" | "";
  schedulerLabel?: string;
  similarityScore?: number | null;
  runDir?: string;
  timestamp: string;
}

export interface WorkspaceStateResponse {
  devices: ApiDevice[];
  selectedDevice: ApiDevice | null;
  latestJob: JobInfo | null;
  executionMode: "planned" | "quick" | "";
  subtaskSource: "planned" | "quick" | "none";
  planSummary: string;
  subtasks: WorkspaceSubtask[];
  currentAction: CurrentAction;
  liveScreenshot: LiveScreenshot;
  evidence: EvidenceItem[];
  auditSessions: AuditSession[];
}

export interface ReportResponse {
  ok: boolean;
  reportPath: string;
  downloadUrl: string;
  summary: { evidenceItems: number; auditSessions: number };
}

export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers: {
        "content-type": "application/json",
        ...(init?.headers ?? {}),
      },
    });
  } catch (err) {
    throw new ApiError(`无法连接后端 API：${err instanceof Error ? err.message : String(err)}`, 0);
  }
  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`;
    try {
      const payload = await response.json();
      message = payload.detail || payload.error || message;
    } catch {
      // Keep HTTP status text.
    }
    throw new ApiError(message, response.status);
  }
  if (response.status === 204) {
    return {} as T;
  }
  return response.json() as Promise<T>;
}

export const api = {
  health: () => request<HealthResponse>("/api/health"),
  dashboard: () => request<DashboardResponse>("/api/dashboard"),
  devices: () => request<{ devices: ApiDevice[] }>("/api/devices"),
  apps: (deviceSerial = "") => request<{ apps: ApiAppInfo[] }>(`/api/apps${deviceSerial ? `?device_serial=${encodeURIComponent(deviceSerial)}` : ""}`),
  workspaceState: (includeScreenshot = true, deviceSerial = "") =>
    request<WorkspaceStateResponse>(
      `/api/workspace-state?include_screenshot=${includeScreenshot ? "true" : "false"}${deviceSerial ? `&device_serial=${encodeURIComponent(deviceSerial)}` : ""}`,
    ),
  liveScreenshot: (deviceSerial = "") =>
    request<{ screenshot: LiveScreenshot }>(`/api/device/live-screenshot${deviceSerial ? `?device_serial=${encodeURIComponent(deviceSerial)}` : ""}`),
  currentAction: () => request<{ currentAction: CurrentAction }>("/api/current-action"),
  createPlan: (payload: {
    case_name: string;
    case_type: string;
    case_background: string;
    forensic_goals: string;
    device_serial?: string;
    allow_fallback?: boolean;
  }) => request<PlanResponse>("/api/plans", { method: "POST", body: JSON.stringify(payload) }),
  startTask: (payload: {
    plan: ForensicPlan;
    device_serial?: string;
    app_name?: string;
    task_index?: number | null;
    threshold?: number;
    execution_mode?: "planned" | "quick";
    case_name?: string;
  }) => request<{ ok: boolean; job: JobInfo }>("/api/tasks/start", { method: "POST", body: JSON.stringify(payload) }),
  startQuickTask: (payload: {
    task_description: string;
    device_serial?: string;
    app_name?: string;
    package_name?: string;
    task_level?: number;
    task_type?: string;
    constraint?: string;
    threshold?: number;
    case_name?: string;
  }) => request<{ ok: boolean; job: JobInfo }>("/api/tasks/quick", { method: "POST", body: JSON.stringify(payload) }),
  jobs: () => request<{ jobs: JobInfo[] }>("/api/jobs"),
  jobDetail: (jobId: string) => request<JobDetailResponse>(`/api/jobs/${jobId}`),
  evidence: () => request<{ evidence: EvidenceItem[] }>("/api/evidence"),
  audit: () => request<{ sessions: AuditSession[] }>("/api/audit"),
  screenshots: () => request<{ screenshots: ScreenshotItem[] }>("/api/screenshots"),
  createReport: (payload: { run_dir?: string; title?: string } = {}) =>
    request<ReportResponse>("/api/reports", { method: "POST", body: JSON.stringify(payload) }),
};

export function apiUrl(path: string) {
  return `${API_BASE}${path}`;
}
