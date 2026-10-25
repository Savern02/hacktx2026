"use client";

import { useState } from "react";
import { ChevronDown } from "lucide-react";

import type { BalanceRead } from "@/app/clientService";
import { fetchBalance } from "@/components/actions/balance-action";
import { RingArc } from "@/components/dashboard/spending-ring";
import { CACHE_KEYS, useCached } from "@/lib/data-cache";
import { cn } from "@/lib/utils";
import { InfoTooltip } from "@/components/ui/info-tooltip";
import { useFirstName } from "@/lib/use-first-name";

const usd = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
});

const NEXT_BILLS = 2;

const shortDate = new Intl.DateTimeFormat("en-US", {
  month: "short",
  day: "numeric",
  timeZone: "UTC",
});

// Share of the balance left after bills.
function getLiquidity(balance: number, safeToSpend: number) {
  const fill =
    balance > 0 ? Math.min(Math.max(safeToSpend / balance, 0), 1) : 0;
  if (safeToSpend < 0 || fill < 0.15)
    return {
      // Negative: a full red ring so the shortfall reads at a glance.
      fill: safeToSpend < 0 ? 1 : fill,
      cue:
        safeToSpend < 0
          ? "Heads up: your bills are more than your balance"
          : "Running low. Equa can help you find support.",
      ring: "text-red-600 dark:text-red-500",
      text: "text-red-700 dark:text-red-400",
    };
  if (fill < 0.4)
    return {
      fill,
      cue: "Things are tight, so spend carefully",
      ring: "text-amber-500 dark:text-amber-400",
      text: "text-amber-700 dark:text-amber-400",
    };
  return {
    fill,
    cue: "Nice! Your bills are covered",
    ring: "text-emerald-600 dark:text-emerald-400",
    text: "text-emerald-700 dark:text-emerald-400",
  };
}

type State =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "not-connected" }
  | { kind: "ready"; data: BalanceRead };

function toState(result: Awaited<ReturnType<typeof fetchBalance>>): State {
  if ("data" in result) return { kind: "ready", data: result.data };
  if ("notConnected" in result) return { kind: "not-connected" };
  return { kind: "error", message: result.message };
}

export function SafeToSpendRing({ className }: { className?: string }) {
  const { result, reload } = useCached(CACHE_KEYS.balance, fetchBalance);
  const state: State = result ? toState(result) : { kind: "loading" };
  const load = () => void reload();
  const firstName = useFirstName();

  const [open, setOpen] = useState(false);
  const [showAllBills, setShowAllBills] = useState(false);
  const loading = state.kind === "loading";
  const data = state.kind === "ready" ? state.data : null;
  const liquidity = data
    ? getLiquidity(data.balance, data.safe_to_spend)
    : null;
  const hiddenBills = data ? data.upcoming_bills.slice(NEXT_BILLS) : [];
  // Bills come sorted by due date, so the last one ends the cycle.
  const lastBillDue = data?.upcoming_bills.at(-1)?.due_date ?? "";

  return (
    <section
      aria-busy={loading}
      className={cn(
        "flex flex-col items-center gap-4 rounded-lg border bg-card p-4 text-center sm:p-6",
        className,
      )}
    >
      {firstName ? (
        <h2 className="text-xl font-semibold">Hi {firstName}!</h2>
      ) : null}
      {/* Tap the ring for the details: the balance math and the next bills. */}
      <button
        type="button"
        disabled={!data}
        onClick={() => setOpen((o) => !o)}
        aria-expanded={data ? open : undefined}
        aria-controls="safe-to-spend-details"
        className="flex flex-col items-center gap-1 rounded-full p-1 transition-colors enabled:hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-default"
      >
        <div
          role="progressbar"
          aria-label="Safe to spend"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={
            data && liquidity
              ? data.safe_to_spend < 0
                ? 0
                : Math.round(liquidity.fill * 100)
              : undefined
          }
          aria-valuetext={
            data && liquidity
              ? `${usd.format(data.safe_to_spend)} safe to spend, ${liquidity.cue}`
              : state.kind === "not-connected"
                ? "No bank connected"
                : "Loading"
          }
          className="relative size-44 shrink-0 sm:size-48"
        >
          <RingArc
            fill={liquidity?.fill ?? 0}
            colorClass={liquidity?.ring ?? "text-muted-foreground/40"}
            spinning={loading}
          />
          <div
            aria-hidden="true"
            className="absolute inset-0 flex flex-col items-center justify-center gap-1"
          >
            <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              Safe to spend
            </span>
            {data ? (
              <span
                className={cn(
                  "text-2xl font-bold tabular-nums",
                  data.safe_to_spend < 0 ? liquidity?.text : "text-foreground",
                )}
              >
                {usd.format(data.safe_to_spend)}
              </span>
            ) : (
              <span
                className={cn(
                  "h-8 w-24 rounded-md bg-muted",
                  loading && "animate-pulse",
                )}
              />
            )}
          </div>
        </div>
      </button>

      {state.kind === "not-connected" ? (
        <p className="max-w-sm text-sm text-muted-foreground">
          Equa doesn&apos;t see a bank yet. Open{" "}
          <span className="font-medium text-foreground">Settings</span> and tap
          &ldquo;Connect to bank&rdquo; so I can show what&apos;s safe to spend.
        </p>
      ) : state.kind === "error" ? (
        <div className="flex flex-col items-center gap-3">
          <p className="text-sm text-muted-foreground">{state.message}</p>
          <button
            type="button"
            onClick={load}
            className="min-h-11 rounded-md border px-4 text-sm font-medium hover:bg-accent"
          >
            Let&apos;s try again
          </button>
        </div>
      ) : data && liquidity ? (
        <div className="flex w-full max-w-sm flex-col items-center gap-3">
          <p className={cn("text-sm font-medium", liquidity.text)}>
            {liquidity.cue}
          </p>
          <button
            type="button"
            onClick={() => setOpen((o) => !o)}
            aria-expanded={open}
            aria-controls="safe-to-spend-details"
            className="inline-flex min-h-11 items-center gap-1 rounded-md px-3 text-xs text-muted-foreground hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            {open ? "Less" : "See how this adds up"}
            <ChevronDown
              aria-hidden="true"
              className={cn(
                "h-3.5 w-3.5 transition-transform motion-reduce:transition-none",
                open && "rotate-180",
              )}
            />
          </button>
          <div
            id="safe-to-spend-details"
            hidden={!open}
            className="flex w-full flex-col gap-3"
          >
            <p className="text-sm text-muted-foreground">
              {usd.format(data.balance)} in checking, minus{" "}
              {usd.format(data.upcoming_bills_total)} in upcoming bills{" "}
              <InfoTooltip
                label="What is safe to spend?"
                text="Your balance minus bills due in the next month. The rest is yours to use."
              />
            </p>
            <ul
              id="upcoming-bills-list"
              className="divide-y rounded-md border text-left text-sm"
            >
              {/* The next few by default; expand to see every bill through the end of
                  this cycle (the same bills the total above counts). */}
              {(showAllBills
                ? data.upcoming_bills
                : data.upcoming_bills.slice(0, NEXT_BILLS)
              ).map((bill) => (
                <li
                  key={`${bill.name}-${bill.due_date}`}
                  className="flex items-center justify-between gap-3 px-3 py-2"
                >
                  <span className="min-w-0">
                    <span className="block truncate font-medium">
                      {bill.name}
                    </span>
                    <span className="text-xs text-muted-foreground">
                      Due {shortDate.format(new Date(bill.due_date))}
                    </span>
                  </span>
                  <span className="shrink-0 tabular-nums">
                    {usd.format(bill.amount)}
                  </span>
                </li>
              ))}
              {hiddenBills.length > 0 ? (
                <li>
                  <button
                    type="button"
                    onClick={() => setShowAllBills((s) => !s)}
                    aria-expanded={showAllBills}
                    aria-controls="upcoming-bills-list"
                    className="flex min-h-11 w-full items-center justify-between gap-2 px-3 py-2 text-left text-xs text-muted-foreground hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
                  >
                    <span>
                      {showAllBills
                        ? "Show fewer"
                        : `+${hiddenBills.length} more ${
                            hiddenBills.length === 1 ? "bill" : "bills"
                          } through ${shortDate.format(new Date(lastBillDue))} (${usd.format(
                            hiddenBills.reduce((sum, b) => sum + b.amount, 0),
                          )})`}
                    </span>
                    <ChevronDown
                      aria-hidden="true"
                      className={cn(
                        "h-3.5 w-3.5 shrink-0 transition-transform motion-reduce:transition-none",
                        showAllBills && "rotate-180",
                      )}
                    />
                  </button>
                </li>
              ) : null}
            </ul>
          </div>
        </div>
      ) : (
        // Skeleton matching the loaded layout so nothing jumps.
        <div className="flex w-full max-w-sm animate-pulse flex-col items-center gap-3">
          <span className="h-5 w-28 rounded bg-muted" />
          <span className="h-5 w-40 max-w-full rounded bg-muted" />
        </div>
      )}
    </section>
  );
}
