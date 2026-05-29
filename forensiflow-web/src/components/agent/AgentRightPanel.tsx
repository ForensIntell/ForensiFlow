import { useState } from "react";
import { DecisionTab } from "./DecisionTab";
import { EvidenceTab } from "./EvidenceTab";
import { AuditTab } from "./AuditTab";

const tabs = ["决策过程", "证据采集", "审计记录"] as const;
type TabKey = (typeof tabs)[number];

export default function AgentRightPanel() {
  const [activeTab, setActiveTab] = useState<TabKey>("决策过程");

  return (
    <div className="flex flex-col h-full">
      {/* Tab bar */}
      <div className="flex items-center gap-1 border-b border-border px-3 py-2">
        {tabs.map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`rounded-full px-3 py-1.5 text-xs font-medium transition-colors ${
              activeTab === tab
                ? "bg-accent-soft text-accent"
                : "text-text-muted hover:bg-black/[.03]"
            }`}
          >
            {tab}
          </button>
        ))}
      </div>

      {/* Content area */}
      <div className="flex-1 overflow-y-auto p-4">
        {activeTab === "决策过程" && <DecisionTab />}
        {activeTab === "证据采集" && <EvidenceTab />}
        {activeTab === "审计记录" && <AuditTab />}
      </div>
    </div>
  );
}
