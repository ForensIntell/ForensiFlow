import { CheckCircle, WarningCircle, Info, XCircle } from "@phosphor-icons/react";

type Tone = "info" | "success" | "warning" | "danger";

const toneClass: Record<Tone, string> = {
  info: "border-info/20 bg-info-soft text-info",
  success: "border-success/20 bg-success-soft text-success",
  warning: "border-warning/20 bg-warning-soft text-warning",
  danger: "border-danger/20 bg-danger-soft text-danger",
};

const toneIcon = {
  info: Info,
  success: CheckCircle,
  warning: WarningCircle,
  danger: XCircle,
};

export function StatusBanner({ tone = "info", title, description }: { tone?: Tone; title: string; description?: string }) {
  const Icon = toneIcon[tone];
  return (
    <div className={`flex items-start gap-2 rounded-xl border px-3 py-2.5 text-sm ${toneClass[tone]}`}>
      <Icon size={16} className="mt-0.5 shrink-0" weight={tone === "info" ? "regular" : "fill"} />
      <div className="min-w-0">
        <p className="font-medium leading-snug">{title}</p>
        {description && <p className="mt-0.5 text-xs leading-relaxed opacity-80">{description}</p>}
      </div>
    </div>
  );
}
