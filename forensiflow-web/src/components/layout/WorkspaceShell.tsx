import type { ReactNode } from "react";

interface Props {
  left: ReactNode;
  center: ReactNode;
  right: ReactNode;
  bottom: ReactNode;
}

export function WorkspaceShell({ left, center, right, bottom }: Props) {
  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      <div className="flex-1 grid grid-cols-1 md:grid-cols-[280px_1fr_360px] xl:grid-cols-[300px_1fr_380px] overflow-hidden">
        {/* Left panel */}
        <aside className="hidden md:flex flex-col border-r border-border bg-surface overflow-y-auto scrollbar-thin">
          {left}
        </aside>

        {/* Center viewport */}
        <main className="relative flex flex-col overflow-hidden bg-bg-subtle">
          {center}
        </main>

        {/* Right panel */}
        <section className="hidden md:flex flex-col border-l border-border bg-surface overflow-y-auto scrollbar-thin">
          {right}
        </section>
      </div>

      {/* Bottom timeline */}
      <footer className="border-t border-border bg-surface shrink-0">
        {bottom}
      </footer>
    </div>
  );
}
