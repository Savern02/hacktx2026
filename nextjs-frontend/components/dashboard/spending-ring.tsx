"use client";

import { useId, useState } from "react";
import { ChevronDown } from "lucide-react";

import { cn } from "@/lib/utils";

/*
 * Circular budget ring for one spending category, e.g. "Groceries: $120 of $200".
 *
 * The mount animation is a CSS keyframe (hoisted once via React 19's
 * <style precedence>). Client component because rings can expand on tap.
 * Later value changes on a client re-render animate via a CSS transition.
 */

export type SpendingRingSize = "sm" | "md" | "lg";
export type SpendingStatus = "on-track" | "near-limit" | "over" | "no-budget";

export interface SpendingRingProps {
  label: string;
  spent: number;
  limit: number;
  size?: SpendingRingSize;
  /** When set, the ring shows only its number and label until tapped. */
  details?: React.ReactNode;
  className?: string;
}

export interface SpendingRingItem {
  /** Stable key; falls back to `label`. */
  id?: string | number;
  label: string;
  spent: number;
  limit: number;
  details?: React.ReactNode;
}

export interface SpendingRingGridProps {
  items: SpendingRingItem[];
  size?: SpendingRingSize;
  className?: string;
}

// Status thresholds (fraction of the budget used).
const NEAR_LIMIT_AT = 0.75;

const STATUS_STYLES: Record<
  SpendingStatus,
  { cue: string; ring: string; text: string }
> = {
  "on-track": {
    cue: "On track",
    ring: "text-emerald-600 dark:text-emerald-400",
    text: "text-emerald-700 dark:text-emerald-400",
  },
  "near-limit": {
    cue: "Close to limit",
    ring: "text-amber-500 dark:text-amber-400",
    text: "text-amber-700 dark:text-amber-400",
  },
  over: {
    cue: "Over budget",
    ring: "text-red-600 dark:text-red-500",
    text: "text-red-700 dark:text-red-400",
  },
  "no-budget": {
    cue: "No budget set",
    ring: "text-muted-foreground",
    text: "text-muted-foreground",
  },
};

const SIZE_STYLES: Record<SpendingRingSize, { ring: string; pct: string }> = {
  sm: { ring: "size-20", pct: "text-base" },
  md: { ring: "size-24", pct: "text-lg" },
  lg: { ring: "size-32", pct: "text-2xl" },
};

const usdWhole = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  maximumFractionDigits: 0,
});
const usdCents = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

export function formatUsd(value: number): string {
  return Number.isInteger(value)
    ? usdWhole.format(value)
    : usdCents.format(value);
}

export function getSpendingStatus(spent: number, limit: number) {
  const safeSpent = Number.isFinite(spent) ? Math.max(spent, 0) : 0;
  const hasBudget = Number.isFinite(limit) && limit > 0;

  if (!hasBudget) {
    return {
      status: "no-budget" as SpendingStatus,
      percent: null,
      // Any spending without a budget fills the ring; nothing spent leaves it empty.
      fill: safeSpent > 0 ? 1 : 0,
    };
  }

  const ratio = safeSpent / limit;
  const status: SpendingStatus =
    ratio > 1 ? "over" : ratio >= NEAR_LIMIT_AT ? "near-limit" : "on-track";

  return {
    status,
    // True (unclamped) value for display, e.g. 130.
    percent: Math.round(ratio * 100),
    // Arc fill, clamped to a full ring.
    fill: Math.min(ratio, 1),
  };
}

// The arc uses pathLength=100, so dash values are plain percentages.
const RING_KEYFRAMES =
  "@keyframes spending-ring-fill{from{stroke-dashoffset:100}}";

/** Track + progress arc filling its parent; `fill` is 0–1. */
export function RingArc({
  fill,
  colorClass,
  spinning = false,
}: {
  fill: number;
  colorClass: string;
  /** Loading state: a short arc that spins instead of showing progress. */
  spinning?: boolean;
}) {
  const shown = spinning ? 0.25 : fill;
  return (
    <>
      <style href="spending-ring-keyframes" precedence="default">
        {RING_KEYFRAMES}
      </style>
      <svg
        viewBox="0 0 100 100"
        className={cn(
          "size-full",
          spinning && "animate-spin motion-reduce:animate-pulse",
        )}
        aria-hidden="true"
        focusable="false"
      >
        <circle
          cx="50"
          cy="50"
          r="42"
          fill="none"
          strokeWidth="9"
          className="stroke-muted"
        />
        {shown > 0 && (
          <circle
            cx="50"
            cy="50"
            r="42"
            fill="none"
            strokeWidth="9"
            strokeLinecap="round"
            pathLength={100}
            strokeDasharray="100 100"
            strokeDashoffset={100 - shown * 100}
            // Start at 12 o'clock and go clockwise.
            transform="rotate(-90 50 50)"
            className={cn(
              "stroke-current",
              colorClass,
              !spinning &&
                "animate-[spending-ring-fill_700ms_ease-out] transition-[stroke-dashoffset] duration-700 ease-out",
              "motion-reduce:animate-none motion-reduce:transition-none",
            )}
          />
        )}
      </svg>
    </>
  );
}

export function SpendingRing({
  label,
  spent,
  limit,
  size = "md",
  details,
  className,
}: SpendingRingProps) {
  const { status, percent, fill } = getSpendingStatus(spent, limit);
  const styles = STATUS_STYLES[status];
  const sizes = SIZE_STYLES[size];
  const hasBudget = percent !== null;
  // With details, the ring starts small (number + label) and expands on tap.
  const expandable = details !== undefined;
  const [open, setOpen] = useState(false);
  const detailsId = useId();

  const ariaLabel = hasBudget
    ? `${label}: ${percent}% of budget used`
    : `${label}: no budget set`;

  const ring = (
    <div
      role="progressbar"
      aria-label={ariaLabel}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={hasBudget ? Math.min(percent, 100) : undefined}
      aria-valuetext={
        hasBudget ? `${percent}% used, ${styles.cue}` : styles.cue
      }
      className={cn("relative shrink-0", sizes.ring)}
    >
      <RingArc fill={fill} colorClass={styles.ring} />
      <span
        aria-hidden="true"
        className={cn(
          "absolute inset-0 flex items-center justify-center font-semibold tabular-nums text-foreground",
          sizes.pct,
        )}
      >
        {hasBudget ? `${percent}%` : "--"}
      </span>
    </div>
  );

  const summary = (
    <>
      <p className="text-sm tabular-nums text-muted-foreground">
        {hasBudget
          ? `${formatUsd(spent)} of ${formatUsd(limit)}`
          : `${formatUsd(spent)} spent`}
      </p>
      <p className={cn("text-xs font-medium", styles.text)}>{styles.cue}</p>
    </>
  );

  if (!expandable) {
    return (
      <div
        className={cn(
          "flex min-w-0 flex-col items-center gap-2 text-center",
          className,
        )}
      >
        {ring}
        <div className="flex min-w-0 max-w-full flex-col gap-0.5">
          <p className="line-clamp-2 break-words text-sm font-medium text-foreground">
            {label}
          </p>
          {summary}
        </div>
      </div>
    );
  }

  return (
    <div
      className={cn(
        "flex min-w-0 flex-col items-center gap-2 text-center",
        className,
      )}
    >
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        aria-controls={detailsId}
        className="group flex min-w-0 flex-col items-center gap-2 rounded-xl p-2 transition-colors hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        {ring}
        <span className="line-clamp-2 break-words text-sm font-medium text-foreground">
          {label}
        </span>
        <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
          {open ? "Less" : "More"}
          <ChevronDown
            aria-hidden="true"
            className={cn(
              "h-3.5 w-3.5 transition-transform motion-reduce:transition-none",
              open && "rotate-180",
            )}
          />
        </span>
      </button>
      <div
        id={detailsId}
        hidden={!open}
        className="flex min-w-0 max-w-full flex-col items-center gap-1"
      >
        {summary}
        <div className="mt-1 text-sm text-foreground">{details}</div>
      </div>
    </div>
  );
}

/**
 * Lays out several rings: 2 columns on phones, 3 from `sm`, 4 from `lg`.
 * Drop it inside a Card (or any container); it never overflows horizontally.
 */
export function SpendingRingGrid({
  items,
  size = "md",
  className,
}: SpendingRingGridProps) {
  return (
    <ul
      className={cn(
        // 2 per row, or 4 in a row on wide screens, so a row is never lopsided.
        "grid grid-cols-2 items-start justify-items-center gap-x-4 gap-y-6 lg:grid-cols-4",
        className,
      )}
    >
      {items.map((item) => (
        <li key={item.id ?? item.label} className="min-w-0">
          <SpendingRing
            label={item.label}
            spent={item.spent}
            limit={item.limit}
            size={size}
            details={item.details}
          />
        </li>
      ))}
    </ul>
  );
}
