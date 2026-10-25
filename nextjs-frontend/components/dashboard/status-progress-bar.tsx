import {
  CheckCircle2,
  Clock,
  MinusCircle,
  type LucideIcon,
} from "lucide-react";

import { cn } from "@/lib/utils";

export type ProgressStatus = "in-progress" | "complete" | "not-applicable";

export interface StatusProgressBarProps {
  status: ProgressStatus;
  /** Optional title shown above the bar, e.g. "SNAP application". */
  label?: string;
  /** Optional icon shown before the label (decorative). */
  icon?: LucideIcon;
  className?: string;
}

const STATUS_CONFIG = {
  "in-progress": {
    text: "In progress…",
    ariaText: "in progress",
    Icon: Clock,
    bar: "bg-red-500 dark:bg-red-500",
    tone: "text-red-600 dark:text-red-400",
  },
  complete: {
    text: "Complete",
    ariaText: "complete",
    Icon: CheckCircle2,
    bar: "bg-green-600 dark:bg-green-500",
    tone: "text-green-700 dark:text-green-400",
  },
  "not-applicable": {
    text: "Not applicable",
    ariaText: "not applicable",
    Icon: MinusCircle,
    bar: "bg-gray-400 dark:bg-gray-600",
    tone: "text-muted-foreground",
  },
} as const satisfies Record<
  ProgressStatus,
  {
    text: string;
    ariaText: string;
    Icon: typeof Clock;
    bar: string;
    tone: string;
  }
>;

export function StatusProgressBar({
  status,
  label,
  icon: LabelIcon,
  className,
}: StatusProgressBarProps) {
  const { text, ariaText, Icon, bar, tone } = STATUS_CONFIG[status];
  const ariaLabel = label ? `${label}: ${ariaText}` : `Status: ${ariaText}`;

  return (
    <div
      role="status"
      aria-label={ariaLabel}
      className={cn("flex w-full min-w-0 flex-col gap-2", className)}
    >
      <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
        {label ? (
          <span className="flex min-w-0 items-center gap-2 break-words text-base font-bold text-foreground sm:text-sm">
            {LabelIcon ? (
              <LabelIcon aria-hidden="true" className="h-5 w-5 shrink-0" />
            ) : null}
            <span className="min-w-0">{label}</span>
          </span>
        ) : null}
        <span
          className={cn(
            "inline-flex items-center gap-1.5 text-sm font-medium",
            tone,
          )}
        >
          <Icon aria-hidden="true" className="h-4 w-4 shrink-0" />
          {text}
        </span>
      </div>
      <div
        aria-hidden="true"
        className="h-3 w-full overflow-hidden rounded-full bg-muted sm:h-2.5"
      >
        <div
          className={cn(
            "h-full w-full rounded-full transition-colors duration-300 motion-reduce:transition-none",
            bar,
          )}
        />
      </div>
    </div>
  );
}
