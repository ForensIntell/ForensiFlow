import { Routes, Route, NavLink } from "react-router-dom";
import { DashboardPage } from "./pages/DashboardPage";
import { WorkspacePage } from "./pages/WorkspacePage";
import { CasesPage } from "./pages/CasesPage";
import { NewTaskPage } from "./pages/NewTaskPage";
import { EvidencePage } from "./pages/EvidencePage";
import { AuditPage } from "./pages/AuditPage";
import { ExperiencePage } from "./pages/ExperiencePage";
import { SettingsPage } from "./pages/SettingsPage";
import {
  House,
  Briefcase,
  FolderOpen,
  Plus,
  Archive,
  ClockCounterClockwise,
  Books,
  Gear,
} from "@phosphor-icons/react";

const navItems = [
  { to: "/", label: "Dashboard", icon: House },
  { to: "/cases", label: "案件管理", icon: FolderOpen },
  { to: "/task/new", label: "新建任务", icon: Plus },
  { to: "/workspace", label: "取证工作台", icon: Briefcase },
  { to: "/evidence", label: "证据库", icon: Archive },
  { to: "/audit", label: "审计回放", icon: ClockCounterClockwise },
  { to: "/experience", label: "经验库", icon: Books },
  { to: "/settings", label: "设置", icon: Gear },
];

function AppShell() {
  return (
    <nav className="flex items-center gap-1 border-b border-border bg-surface px-4 py-1.5 overflow-x-auto">
      {navItems.map((item) => (
        <NavLink
          key={item.to}
          to={item.to}
          end={item.to === "/"}
          className={({ isActive }) =>
            `inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs whitespace-nowrap transition ${
              isActive
                ? "bg-accent-soft text-accent"
                : "text-text-muted hover:bg-bg hover:text-text"
            }`
          }
        >
          <item.icon size={14} />
          {item.label}
        </NavLink>
      ))}
    </nav>
  );
}

export default function App() {
  return (
    <div className="min-h-[100dvh] flex flex-col">
      <AppShell />
      <div className="flex-1">
        <Routes>
          <Route path="/" element={<DashboardPage />} />
          <Route path="/cases" element={<CasesPage />} />
          <Route path="/task/new" element={<NewTaskPage />} />
          <Route path="/workspace" element={<WorkspacePage />} />
          <Route path="/evidence" element={<EvidencePage />} />
          <Route path="/audit" element={<AuditPage />} />
          <Route path="/experience" element={<ExperiencePage />} />
          <Route path="/settings" element={<SettingsPage />} />
        </Routes>
      </div>
    </div>
  );
}
