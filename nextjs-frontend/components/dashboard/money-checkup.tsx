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

  return (
    <section className="grid gap-4" aria-labelledby="checkup-heading">
      <div>
        <h2 id="checkup-heading" className="text-lg font-semibold">
          Your money check-up
        </h2>
        <p className="text-sm text-muted-foreground">
          From your last 8 weeks: about {formatUsd(Math.round(income))} comes in
          each month.
        </p>
      </div>

      <SpendingRingGrid
        items={[
          {
            id: "needs",
            label: "Needs (goal 50%)",
            spent: needs.amount,
            limit: income * 0.5,
          },
          {
            id: "wants",
            label: "Wants (goal 30%)",
            spent: wants.amount,
            limit: income * 0.3,
          },
          {
            id: "housing",
            label: "Housing (limit 28%)",
            spent: housing.amount,
            limit: income * 0.28,
          },
          {
            id: "debt",
            label: "Housing + debt (limit 36%)",
            spent: debt.amount,
            limit: income * 0.36,
          },
        ]}
      />

      <ul className="grid gap-2 rounded-lg border bg-card p-4">
        <Check ok={needs.ok}>
          Needs take {share(needs.pct)} of your income. The 50/30/20 rule aims
          for 50%.{" "}
          <InfoTooltip
            label="What is the 50/30/20 rule?"
            align="end"
            text="50% on needs, 30% on wants, 20% on savings."
          />
        </Check>
        <Check ok={savings.ok}>
          {savings.amount > 0
            ? `You keep about ${formatUsd(Math.round(savings.amount))} a month (${share(savings.pct)}). The goal is 20%.`
            : "Nothing is left over to save each month yet. The goal is 20%."}
        </Check>
        <Check ok={housing.ok}>
          Housing is {share(housing.pct)} of your income. The 28/36 rule says
          28% or less.{" "}
          <InfoTooltip
            label="What is the 28/36 rule?"
            align="end"
            text="Keep rent under 28% of income, and rent plus debt under 36%."
          />
        </Check>
        <Check ok={debt.ok}>
          Housing plus loan payments are {share(debt.pct)}. The 28/36 rule says
          36% or less.
        </Check>
      </ul>
      <p className="text-xs text-muted-foreground">{h.income_note}</p>
    </section>
  );
}
