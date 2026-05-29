import { OverlayCanvas } from "./OverlayCanvas";
import { PageSummaryBar } from "./PageSummaryBar";
import { api, apiUrl } from "../../lib/api";
import { usePollingData } from "../../lib/hooks";

export function DeviceViewport() {
  const { data, loading, error, refresh } = usePollingData(() => api.workspaceState(true), 4000, []);
  const screenshot = data?.liveScreenshot;
  const device = data?.selectedDevice;
  const screenshotUrl = screenshot?.ok && screenshot.url ? `${apiUrl(screenshot.url)}&t=${encodeURIComponent(screenshot.capturedAt ?? "")}` : "";

  return (
    <div className="flex flex-col h-full">
      <PageSummaryBar state={data ?? null} />

      <div className="flex-1 flex items-center justify-center p-4 overflow-hidden">
        {/* Phone bezel */}
        <div className="phone-bezel max-h-full" style={{ width: "min(320px, 90vw)" }}>
          <div className="phone-screen relative" style={{ aspectRatio: "9/19.5" }}>
            {/* Device screenshot */}
            {screenshotUrl ? (
              <img
                src={screenshotUrl}
                alt={`Live capture from ${screenshot?.serial || "connected device"}`}
                className="absolute inset-0 w-full h-full object-cover"
              />
            ) : (
              <div className="absolute inset-0 flex flex-col items-center justify-center bg-[#10131f] px-8 text-center text-white/70">
                <p className="text-sm font-medium">{loading ? "正在读取连接设备..." : device?.status === "connected" ? "实时截图不可用" : "暂无连接手机"}</p>
                <p className="mt-2 text-xs leading-relaxed text-white/45">
                  {error || screenshot?.error || "连接 ADB 设备后，这里直接显示当前手机屏幕。"}
                </p>
                <button
                  onClick={refresh}
                  className="mt-4 rounded-lg border border-white/15 px-3 py-1.5 text-xs text-white/80 hover:bg-white/10 transition"
                >
                  重新读取
                </button>
              </div>
            )}

            {/* Overlay: detection boxes */}
            {screenshotUrl && <OverlayCanvas />}

            {/* Status bar simulation */}
            <div className="absolute top-0 left-0 right-0 flex items-center justify-between px-6 py-1.5 text-[9px] text-white/80 bg-gradient-to-b from-black/40 to-transparent">
              <span className="font-medium">9:41</span>
              <span className="max-w-[150px] truncate text-[8px] text-white/65">{device?.serial || screenshot?.serial || "ADB"}</span>
              <div className="flex items-center gap-1">
                <span className="w-3 h-1.5 border border-white/60 rounded-sm relative">
                  <span className="absolute inset-0.5 bg-white/80 rounded-[1px]" style={{ width: "60%" }} />
                </span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
