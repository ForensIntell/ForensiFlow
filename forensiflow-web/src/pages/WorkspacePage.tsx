import { AppTopbar } from "../components/layout/AppTopbar";
import { WorkspaceShell } from "../components/layout/WorkspaceShell";
import CaseSidebar from "../components/case/CaseSidebar";
import { DeviceViewport } from "../components/device/DeviceViewport";
import AgentRightPanel from "../components/agent/AgentRightPanel";
import { BottomTimeline } from "../components/timeline/BottomTimeline";

export function WorkspacePage() {
  return (
    <div className="min-h-[100dvh] flex flex-col bg-bg">
      <AppTopbar />
      <WorkspaceShell
        left={<CaseSidebar />}
        center={<DeviceViewport />}
        right={<AgentRightPanel />}
        bottom={<BottomTimeline />}
      />
    </div>
  );
}
