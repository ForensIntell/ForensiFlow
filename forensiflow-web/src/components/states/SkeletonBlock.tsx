interface SkeletonBlockProps {
  className?: string;
}

export function SkeletonBlock({ className = "" }: SkeletonBlockProps) {
  return (
    <div
      className={`flex flex-col gap-3 p-4 animate-pulse ${className}`}
      aria-hidden="true"
    >
      {/* Row 1 — full width */}
      <div className="h-3.5 w-full rounded bg-border/50" />

      {/* Row 2 — ~75% width */}
      <div className="h-3.5 w-3/4 rounded bg-border/50" />

      {/* Row 3 — ~90% width */}
      <div className="h-3.5 w-[90%] rounded bg-border/50" />

      {/* Row 4 — ~60% width */}
      <div className="h-3.5 w-3/5 rounded bg-border/50" />

      {/* Row 5 — ~80% width */}
      <div className="h-3.5 w-4/5 rounded bg-border/50" />
    </div>
  );
}
