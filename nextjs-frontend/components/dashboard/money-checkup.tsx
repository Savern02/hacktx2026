"use client";

import { CheckCircle2, CircleAlert } from "lucide-react";

import type { FinancialHealth } from "@/app/clientService";
import { fetchFinancialHealth } from "@/components/actions/finance-action";
import {
  formatUsd,
  SpendingRingGrid,
} from "@/components/dashboard/spending-ring";
import { InfoTooltip } from "@/components/ui/info-tooltip";
import { CACHE_KEYS, useCached } from "@/lib/data-cache";

type State =
  | { kind: "loading" }
  | { kind: "not-connected" }
  | { kind: "error"; message: string }
  | { kind: "ready"; data: FinancialHealth };

function Check({ ok, children }: { ok: boolean; children: React.ReactNode }) {
  const Icon = ok ? CheckCircle2 : CircleAlert;
  return (
    <li className="flex items-start gap-2 text-sm">
      <Icon
        aria-hidden="true"
        className={
          ok
            ? "mt-0.5 h-4 w-4 shrink-0 text-emerald-600 dark:text-emerald-400"
            : "mt-0.5 h-4 w-4 shrink-0 text-amber-600 dark:text-amber-400"
        }
      />
      <span>
        <span className="sr-only">
          {ok ? "On track: " : "Needs attention: "}
        </span>
        {children}
      </span>
    </li>
  );
}

export function MoneyCheckup() {
  const { result } = useCached(CACHE_KEYS.health, fetchFinancialHealth);
  const state: State = !result
    ? { kind: "loading" }
    : "data" in result
      ? { kind: "ready", data: result.data }
      : "notConnected" in result
        ? { kind: "not-connected" }
        : { kind: "error", message: result.message };

  if (state.kind === "loading") {
    return (
      <div className="grid animate-pulse gap-4" aria-busy="true">
        <span className="h-6 w-48 rounded bg-muted" />
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          {[0, 1, 2, 3].map((i) => (
            <span key={i} className="mx-auto size-24 rounded-full bg-muted" />
          ))}
        </div>
      </div>
    );
  }
  if (state.kind === "not-connected") {
    return (
      <p className="text-sm text-muted-foreground">
        Connect your bank in Settings and Equa will check your spending against
        the 50/30/20 and 28/36 rules.
      </p>
    );
  }
  if (state.kind === "error") {
    return <p className="text-sm text-muted-foreground">{state.message}</p>;
  }

  const h = state.data;
  const income = h.income_monthly;
  const { needs, wants, savings } = h.rule_50_30_20;
  const { housing, debt } = h.rule_28_36;
  const share = (pct: number | null) =>
    pct === null ? "—" : `${Math.round(pct)}%`;
  const rule503020 = (
    <InfoTooltip
      label="What is the 50/30/20 rule?"
      text="50% on needs, 30% on wants, 20% on savings."
    />
  );
  const rule2836 = (
    <InfoTooltip
      label="What is the 28/36 rule?"
      text="Keep rent under 28% of income, and rent plus debt under 36%."
    />
  );

  return (
    <section
      className="flex flex-col items-center gap-4 text-center"
      aria-labelledby="checkup-heading"
    >
      <div>
        <h2 id="checkup-heading" className="text-lg font-semibold">
          Your money check-up
        </h2>
        <p className="text-sm text-muted-foreground">
          About {formatUsd(Math.round(income))} comes in each month. Tap a
          circle to learn more.
        </p>
      </div>

      {/* Each circle starts with just its number; the explanation is a tap away. */}
      <SpendingRingGrid
        className="w-full"
        items={[
          {
            id: "needs",
            label: "Needs",
            spent: needs.amount,
            limit: income * 0.5,
            details: (
              <>
                Needs take {share(needs.pct)} of your income. The 50/30/20 rule
                aims for 50%. {rule503020}
              </>
            ),
          },
          {
            id: "wants",
            label: "Wants",
            spent: wants.amount,
            limit: income * 0.3,
            details: (
              <>
                Wants take {share(wants.pct)} of your income. The 50/30/20 rule
                allows up to 30%. {rule503020}
              </>
            ),
          },
          {
            id: "housing",
            label: "Housing",
            spent: housing.amount,
            limit: income * 0.28,
            details: (
              <>
                Housing is {share(housing.pct)} of your income. The 28/36 rule
                says 28% or less. {rule2836}
              </>
            ),
          },
          {
            id: "debt",
            label: "Housing + debt",
            spent: debt.amount,
            limit: income * 0.36,
            details: (
              <>
                Housing plus loan payments are {share(debt.pct)}. The 28/36 rule
                says 36% or less. {rule2836}
              </>
            ),
          },
        ]}
      />

      {/* Savings has no circle (more is better), so it gets one centered line. */}
      <ul className="flex justify-center">
        <Check ok={savings.ok}>
          {savings.amount > 0
            ? `You keep about ${formatUsd(Math.round(savings.amount))} a month (${share(savings.pct)}). The goal is 20%.`
            : "Nothing is left over to save each month yet. The goal is 20%."}
        </Check>
      </ul>
      <p className="text-xs text-muted-foreground">{h.income_note}</p>
    </section>
  );
}
