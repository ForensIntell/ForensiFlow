import { CircleDashed } from "@phosphor-icons/react";

interface EmptyStateProps {
  title: string;
  description: string;
}

export function EmptyState({ title, description }: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center justify-center h-full min-h-[240px] px-6 py-12 text-center">
      <CircleDashed
        size={48}
        weight="thin"
        className="text-text-dim mb-4"
      />
      <h3 className="text-sm font-medium text-text-secondary mb-1.5">
        {title}
      </h3>
      <p className="text-xs text-text-dim max-w-xs leading-relaxed">
        {description}
      </p>
    </div>
  );
}
