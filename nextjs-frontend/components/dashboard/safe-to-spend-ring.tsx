"use client";

import { useCallback, useEffect, useState } from "react";

import type { BalanceRead } from "@/app/clientService";
import { fetchBalance } from "@/components/actions/balance-action";
import { RingArc } from "@/components/dashboard/spending-ring";
import { cn } from "@/lib/utils";

const usd = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
});

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
      fill,
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
  const [state, setState] = useState<State>({ kind: "loading" });

  const load = useCallback(async () => {
    setState({ kind: "loading" });
    const result = await fetchBalance();
    setState(toState(result));
  }, []);

  useEffect(() => {
    let cancelled = false;
    fetchBalance().then((result) => {
      if (cancelled) return;
      setState(toState(result));
    });
    return () => {
      cancelled = true;
    };
  }, []);

  const loading = state.kind === "loading";
  const data = state.kind === "ready" ? state.data : null;
  const liquidity = data
    ? getLiquidity(data.balance, data.safe_to_spend)
    : null;

  return (
    <section
      aria-busy={loading}
      className={cn(
        "flex flex-col items-center gap-4 rounded-lg border bg-card p-4 text-center sm:p-6",
        className,
      )}
    >
      <div
        role="progressbar"
        aria-label="Safe to spend"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={liquidity ? Math.round(liquidity.fill * 100) : undefined}
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
            <span className="text-2xl font-bold tabular-nums text-foreground">
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
        <div className="flex w-full max-w-sm flex-col gap-3">
          <p className={cn("text-sm font-medium", liquidity.text)}>
            {liquidity.cue}
          </p>
          <p className="text-sm text-muted-foreground">
            {usd.format(data.balance)} in checking, minus{" "}
            {usd.format(data.upcoming_bills_total)} in upcoming bills
          </p>
          <ul className="divide-y rounded-md border text-left text-sm">
            {data.upcoming_bills.map((bill) => (
              <li
                key={bill.name}
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
          </ul>
        </div>
      ) : (
        // Skeleton matching the loaded layout so nothing jumps.
        <div className="flex w-full max-w-sm animate-pulse flex-col items-center gap-3">
          <span className="h-5 w-28 rounded bg-muted" />
          <span className="h-5 w-64 max-w-full rounded bg-muted" />
          <span className="h-[7.5rem] w-full rounded-md bg-muted" />
        </div>
      )}
    </section>
  );
}
