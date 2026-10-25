import * as React from "react";
import { Info } from "lucide-react";

import { cn } from "@/lib/utils";

type Side = "top" | "bottom";
type Align = "center" | "start" | "end";

interface InfoTooltipProps {
  text: React.ReactNode;
  side?: Side;
  // "start"/"end" keep the box on screen when the icon sits near an edge.
  align?: Align;
  className?: string;
  iconClassName?: string;
  label?: string;
}

const sideClasses: Record<Side, string> = {
  top: "bottom-full mb-2",
  bottom: "top-full mt-2",
};

const alignClasses: Record<Align, string> = {
  center: "left-1/2 -translate-x-1/2",
  start: "left-0",
  end: "right-0",
};

// Pure CSS: shows on hover, and on focus so keyboard and tap (mobile) work too.
export function InfoTooltip({
  text,
  side = "top",
  align = "center",
  className,
  iconClassName,
  label = "More info",
}: InfoTooltipProps) {
  return (
    <span className={cn("group relative inline-flex align-middle", className)}>
      <button
        type="button"
        aria-label={label}
        className={cn(
          "inline-flex h-5 w-5 items-center justify-center rounded-full text-gray-500 transition-colors hover:text-gray-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-gray-400",
          iconClassName,
        )}
      >
        <Info className="h-4 w-4" aria-hidden />
      </button>
      <span
        role="tooltip"
        className={cn(
          // Reset type styles so the box doesn't inherit from big headings around it.
          "pointer-events-none absolute z-50 w-max max-w-[16rem] rounded-md bg-gray-800/80 px-3 py-2 text-left text-xs font-normal normal-case leading-snug tracking-normal text-white shadow-lg backdrop-blur-sm",
          "invisible opacity-0 transition-opacity duration-150 group-hover:visible group-hover:opacity-100 group-focus-within:visible group-focus-within:opacity-100",
          sideClasses[side],
          alignClasses[align],
        )}
      >
        {text}
      </span>
    </span>
  );
}
