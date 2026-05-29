export interface DeviceInCase {
  serial: string;
  model: string;
  status: "connected" | "disconnected" | "processing";
  taskCount: number;
  evidenceCount: number;
  lastActiveAt: string;
}

export interface CaseItem {
  id: string;
  name: string;
  caseType: string;
  status: "active" | "closed" | "pending";
  description: string;
  devices: DeviceInCase[];
  createdAt: string;
  updatedAt: string;
}

export interface EvidenceItem {
  id: string;
  caseId: string;
  deviceSerial: string;
  evidenceType: string;
  summary: string;
  app: string;
  page: string;
  hash: string;
  timestamp: string;
  sourcePath?: string;
  runDir?: string;
  downloadUrl?: string;
  recordCount?: number;
}

export interface AuditStep {
  step: number;
  action: string;
  pageSnapshot?: string;
  modelOutput?: string;
  result?: string;
  hash: string;
  timestamp: string;
}

export interface AuditSession {
  caseId: string;
  caseName: string;
  deviceSerial: string;
  deviceModel: string;
  steps: AuditStep[];
  startedAt: string;
  status: "running" | "completed" | "failed";
}

export interface Subtask {
  id: number;
  label: string;
  status: "pending" | "active" | "done" | "error";
}

export interface AppInfo {
  name: string;
  package: string;
  category: string;
}
