import TaskInput from "./TaskInput";
import { SubtaskList } from "./SubtaskList";
import AppList from "./AppList";
import { RouteScoreBadge } from "./RouteScoreBadge";

export default function CaseSidebar() {
  return (
    <aside className="flex flex-col gap-6 p-5">
      {/* Header */}
      <div className="flex flex-col gap-1.5">
        <span className="text-[11px] font-semibold uppercase tracking-[0.14em] text-text-muted">
          Case Workspace
        </span>
        <h1 className="text-lg font-bold text-text leading-snug">
          ForensiFlow 智能取证工作台
        </h1>
        <p className="text-sm text-accent font-medium">
          实时后端工作区
        </p>
      </div>

      {/* Task Input */}
      <TaskInput />

      {/* Subtask List */}
      <SubtaskList />

      {/* Route Score */}
      <RouteScoreBadge />

      {/* App List */}
      <AppList />
    </aside>
  );
}
