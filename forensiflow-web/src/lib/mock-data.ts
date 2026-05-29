import type { CaseItem, Subtask, AppInfo, EvidenceItem, AuditSession } from "../types/stream";

export const mockCases: CaseItem[] = [
  {
    id: "CASE-2026-001",
    name: "涉嫌诈骗案 - WhatsApp 证据采集",
    caseType: "诈骗",
    status: "active",
    description: "嫌疑人通过 WhatsApp 与多名受害人联系，需提取聊天记录和通话记录。",
    devices: [
      { serial: "<DEVICE_SERIAL>", model: "Redmi K60 Pro", status: "connected", taskCount: 3, evidenceCount: 128, lastActiveAt: "2026-05-18 19:35" },
      { serial: "R5CT10YZ37Z", model: "Samsung Galaxy S23", status: "processing", taskCount: 2, evidenceCount: 56, lastActiveAt: "2026-05-18 18:20" },
    ],
    createdAt: "2026-05-14 10:00",
    updatedAt: "2026-05-18 19:35",
  },
  {
    id: "CASE-2026-002",
    name: "网络赌博案 - Telegram 群组分析",
    caseType: "赌博",
    status: "active",
    description: "涉案 Telegram 群组运营赌博平台，需提取群成员列表和资金往来记录。",
    devices: [
      { serial: "emulator-5554", model: "LDPlayer 9", status: "connected", taskCount: 3, evidenceCount: 67, lastActiveAt: "2026-05-16 18:20" },
    ],
    createdAt: "2026-05-10 14:30",
    updatedAt: "2026-05-16 18:20",
  },
  {
    id: "CASE-2026-003",
    name: "侵犯公民个人信息案",
    caseType: "侵犯隐私",
    status: "pending",
    description: "嫌疑人非法获取并出售公民个人信息，需从多个应用提取相关证据。",
    devices: [
      { serial: "5a3f8e21", model: "Huawei P60", status: "disconnected", taskCount: 4, evidenceCount: 0, lastActiveAt: "-" },
      { serial: "c91b4d77", model: "Xiaomi 14", status: "disconnected", taskCount: 4, evidenceCount: 0, lastActiveAt: "-" },
    ],
    createdAt: "2026-05-18 09:00",
    updatedAt: "2026-05-18 09:00",
  },
  {
    id: "CASE-2026-004",
    name: "毒品交易案 - 暗网通信取证",
    caseType: "毒品",
    status: "closed",
    description: "已完成取证，涉案人员通过 Chrome 浏览器访问暗网市场。",
    devices: [
      { serial: "emulator-5554", model: "LDPlayer 9", status: "disconnected", taskCount: 6, evidenceCount: 312, lastActiveAt: "2026-05-02 17:45" },
    ],
    createdAt: "2026-04-20 08:00",
    updatedAt: "2026-05-02 17:45",
  },
  {
    id: "CASE-2026-005",
    name: "商业间谍案 - Outlook 邮件提取",
    caseType: "商业秘密",
    status: "active",
    description: "嫌疑人涉嫌向外泄露公司商业机密，需从 Outlook 邮件中提取通信记录。",
    devices: [
      { serial: "<DEVICE_SERIAL>", model: "Redmi K60 Pro", status: "connected", taskCount: 2, evidenceCount: 45, lastActiveAt: "2026-05-14 20:16" },
      { serial: "f72e9a33", model: "iPhone 15 Pro", status: "disconnected", taskCount: 2, evidenceCount: 44, lastActiveAt: "2026-05-13 15:30" },
    ],
    createdAt: "2026-05-12 11:00",
    updatedAt: "2026-05-14 20:16",
  },
];

export const caseTypes = [
  "诈骗", "盗窃", "赌博", "毒品", "侵犯隐私", "商业秘密",
  "故意伤害", "敲诈勒索", "非法集资", "其他",
];

export const mockAuditSessions: AuditSession[] = [
  {
    caseId: "CASE-2026-001", caseName: "涉嫌诈骗案", deviceSerial: "<DEVICE_SERIAL>", deviceModel: "Redmi K60 Pro",
    startedAt: "2026-05-18 19:33:00", status: "completed",
    steps: [
      { step: 1, action: "启动取证任务", hash: "e4b1...0001", timestamp: "19:33:00" },
      { step: 2, action: "获取页面 XML", hash: "e4b1...0002", timestamp: "19:33:02", pageSnapshot: "ChatListActivity.xml" },
      { step: 3, action: "模型判断: 点击联系人 kndxx", hash: "e4b1...0003", timestamp: "19:33:05", modelOutput: "点击联系人 kndxx (score=0.91)" },
      { step: 4, action: "执行点击 (324, 856)", hash: "e4b1...0004", timestamp: "19:33:06", result: "OK tapped" },
      { step: 5, action: "采集截图", hash: "e4b1...0005", timestamp: "19:33:08", pageSnapshot: "ChatDetail_kndxx.png" },
      { step: 6, action: "脚本生成与运行", hash: "e4b1...0006", timestamp: "19:34:10", modelOutput: "generated_script.py -> records.json (128条)" },
      { step: 7, action: "证据落盘", hash: "e4b1...0007", timestamp: "19:35:12", result: "写入 records.json (128条)" },
      { step: 8, action: "哈希链更新", hash: "e4b1...0008", timestamp: "19:35:13", result: "prev=e4b1...0007 -> e4b1...0008" },
    ],
  },
  {
    caseId: "CASE-2026-001", caseName: "涉嫌诈骗案", deviceSerial: "R5CT10YZ37Z", deviceModel: "Samsung Galaxy S23",
    startedAt: "2026-05-18 18:10:00", status: "running",
    steps: [
      { step: 1, action: "启动取证任务", hash: "c7a2...0001", timestamp: "18:10:00" },
      { step: 2, action: "获取页面 XML", hash: "c7a2...0002", timestamp: "18:10:03", pageSnapshot: "LauncherActivity.xml" },
      { step: 3, action: "模型判断: 启动 WhatsApp", hash: "c7a2...0003", timestamp: "18:10:06", modelOutput: "launch_app com.whatsapp" },
      { step: 4, action: "等待应用启动", hash: "c7a2...0004", timestamp: "18:10:08", result: "OK launched com.whatsapp" },
      { step: 5, action: "获取聊天列表", hash: "c7a2...0005", timestamp: "18:10:15", pageSnapshot: "ChatListActivity.xml" },
    ],
  },
  {
    caseId: "CASE-2026-004", caseName: "毒品交易案", deviceSerial: "emulator-5554", deviceModel: "LDPlayer 9",
    startedAt: "2026-05-02 14:00:00", status: "completed",
    steps: [
      { step: 1, action: "启动取证任务", hash: "a1f0...0001", timestamp: "14:00:00" },
      { step: 2, action: "启动 Chrome 浏览器", hash: "a1f0...0002", timestamp: "14:00:05", result: "OK launched com.android.chrome" },
      { step: 3, action: "采集浏览历史", hash: "a1f0...0003", timestamp: "14:05:30", result: "提取 312 条历史记录" },
      { step: 4, action: "证据落盘", hash: "a1f0...0004", timestamp: "14:06:00", result: "写入 records.json (312条)" },
    ],
  },
];

export const mockSubtasks: Subtask[] = [
  { id: 1, label: "识别目标应用 WhatsApp", status: "done" },
  { id: 2, label: "进入聊天列表", status: "done" },
  { id: 3, label: "定位目标联系人 kndxx", status: "active" },
  { id: 4, label: "采集聊天记录", status: "pending" },
  { id: 5, label: "生成审计证据包", status: "pending" },
];

export const mockApps: AppInfo[] = [
  { name: "WhatsApp Messenger", package: "com.whatsapp", category: "通讯" },
  { name: "Chrome", package: "com.android.chrome", category: "浏览器" },
  { name: "Telegram", package: "org.telegram.messenger", category: "通讯" },
  { name: "Microsoft Outlook", package: "com.microsoft.office.outlook", category: "邮件" },
];

export const mockEvidence: EvidenceItem[] = [
  { id: "ev-001", caseId: "CASE-2026-001", deviceSerial: "<DEVICE_SERIAL>", evidenceType: "聊天记录", summary: "与 kndxx 的 128 条消息记录", app: "WhatsApp", page: "ChatDetailActivity", hash: "a3f9...7c21", timestamp: "2026-05-18 19:35:12" },
  { id: "ev-002", caseId: "CASE-2026-001", deviceSerial: "<DEVICE_SERIAL>", evidenceType: "通话记录", summary: "5 条语音通话记录", app: "WhatsApp", page: "CallLogActivity", hash: "10b2...d84a", timestamp: "2026-05-18 19:36:04" },
  { id: "ev-003", caseId: "CASE-2026-001", deviceSerial: "R5CT10YZ37Z", evidenceType: "联系人列表", summary: "87 个联系人条目", app: "WhatsApp", page: "ContactListActivity", hash: "cc41...ef09", timestamp: "2026-05-18 18:20:21" },
];

export const mockTimelineSteps = [
  "截图采集", "XML 解析", "模型规划", "目标匹配", "执行动作", "证据落盘", "哈希上链"
];
