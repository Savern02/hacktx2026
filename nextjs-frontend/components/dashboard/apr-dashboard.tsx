"use client";

import { useRef, useState } from "react";
import gsap from "gsap";
import { useGSAP } from "@gsap/react";
import { Check, Copy, ExternalLink, Handshake, Zap } from "lucide-react";

import type { AprImpact, LenderRequest } from "@/app/clientService";
import {
  draftLenderRequest,
  fetchAprImpact,
} from "@/components/actions/finance-action";
import { formatUsd } from "@/components/dashboard/spending-ring";
import { Button } from "@/components/ui/button";
import { InfoTooltip } from "@/components/ui/info-tooltip";
import { CACHE_KEYS, peekCached, setCached, useCached } from "@/lib/data-cache";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

gsap.registerPlugin(useGSAP);

type State =
  | { kind: "loading" }
  | { kind: "not-connected" }
  | { kind: "error"; message: string }
  | { kind: "ready"; data: AprImpact };

const dollars = (n: number) => formatUsd(Math.round(n));

// Black and white like the rest of the app, and no reds or warning icons even
// for a high APR: the goal is to feel empowered, not panicked.
const ICON_CHIP =
  "flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-muted text-foreground";
const ACTION_BUTTON = "min-h-11 w-full sm:w-auto";

function AprHero({ data }: { data: AprImpact }) {
  const loan = data.highest;
  if (!loan) {
    return (
      <section
        data-apr-animate
        className="rounded-2xl bg-primary p-6 text-primary-foreground"
      >
        <p className="text-sm text-primary-foreground/70">
          Your interest rates
        </p>
        <p className="mt-2 text-lg">
          Equa doesn&apos;t see any loans. That&apos;s one less thing draining
          your money.
        </p>
      </section>
    );
  }
  const interestShare =
    loan.monthly_payment > 0
      ? Math.min(loan.monthly_interest / loan.monthly_payment, 1)
      : 0;
  return (
    <section
      data-apr-animate
      aria-labelledby="apr-heading"
      className="grid justify-items-center gap-5 rounded-2xl bg-primary p-6 text-center text-primary-foreground sm:p-8"
    >
      <div>
        <p
          id="apr-heading"
          className="text-sm font-medium text-primary-foreground/70"
        >
          Your highest interest rate
        </p>
        <p className="mt-1 text-6xl font-bold tracking-tight tabular-nums sm:text-7xl">
          {loan.apr}%
          <span className="ml-2 align-middle text-2xl font-semibold text-primary-foreground/70">
            APR
          </span>
          <InfoTooltip
            label="What is APR?"
            align="start"
            iconClassName="text-primary-foreground/70 hover:text-primary-foreground"
            text="What a loan costs you per year. 20% APR on $1,000 is about $200."
          />
        </p>
        <p className="mt-1 text-sm text-primary-foreground/70">{loan.name}</p>
        {/* Nessie loans carry no rate, so every APR is estimated from credit score. */}
        <p className="mt-1 text-xs text-primary-foreground/70">
          {loan.apr_basis}. Check your statement for the exact rate.
        </p>
      </div>
      <div className="grid w-full max-w-md gap-3">
        <p className="text-lg leading-snug">
          This rate costs you about{" "}
          <span className="font-bold underline decoration-2 underline-offset-4">
            {dollars(loan.monthly_interest)} a month
          </span>{" "}
          in interest alone.
        </p>
        {/* Gauge: how much of each payment goes to interest instead of the balance. */}
        <div>
          <div
            role="img"
            aria-label={`${Math.round(interestShare * 100)}% of your ${dollars(loan.monthly_payment)} payment goes to interest`}
            className="h-3 w-full overflow-hidden rounded-full bg-primary-foreground/20"
          >
            <div
              className="h-full rounded-full bg-primary-foreground"
              style={{ width: `${interestShare * 100}%` }}
            />
          </div>
          <p className="mt-2 text-sm text-primary-foreground/70">
            {dollars(loan.monthly_interest)} of your{" "}
            {dollars(loan.monthly_payment)} payment goes to interest. Only{" "}
            {dollars(loan.monthly_payment - loan.monthly_interest)} pays down
            the {dollars(loan.balance)} you owe.{" "}
            <InfoTooltip
              label="Interest vs. principal"
              align="end"
              iconClassName="text-primary-foreground/70 hover:text-primary-foreground"
              text="Interest is the lender's fee. The rest pays down what you owe."
            />
          </p>
        </div>
      </div>
    </section>
  );
}

function LenderCard({ data }: { data: AprImpact }) {
  const loan = data.highest;
  // The draft is cached too, so switching tabs doesn't throw it away (or re-ask Gemini).
  const [draft, setDraftState] = useState<LenderRequest | null>(
    () => peekCached<LenderRequest>(CACHE_KEYS.lenderRequest) ?? null,
  );
  const setDraft = (value: LenderRequest) => {
    setCached<LenderRequest>(CACHE_KEYS.lenderRequest, () => value);
    setDraftState(value);
  };
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);
  if (!loan) return null;

  const negotiate = async () => {
    setBusy(true);
    setError(null);
    const result = await draftLenderRequest();
    setBusy(false);
    if ("data" in result) setDraft(result.data);
    else setError(result.message);
  };

  const copy = async () => {
    if (!draft) return;
    try {
      await navigator.clipboard.writeText(draft.draft);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
    }
  };

  return (
    <Card data-apr-animate className="flex flex-col">
      <CardHeader className="flex-col items-center gap-3 space-y-0 text-center">
        <span className={ICON_CHIP}>
          <Handshake className="h-5 w-5" aria-hidden="true" />
        </span>
        <div className="grid gap-1">
          <CardTitle className="text-lg">
            Ask {loan.lender} for a better rate
          </CardTitle>
          <CardDescription>
            Your {loan.apr}% APR is high for a {loan.type} loan. Lenders often
            have rate reductions or penalty-free deferments for customers who
            ask.{" "}
            <InfoTooltip
              label="What is a deferment?"
              align="end"
              text="A break from payments without hurting your credit."
            />{" "}
            Equa can write the request for you.
          </CardDescription>
        </div>
      </CardHeader>
      {draft ? (
        <CardContent className="grid gap-2">
          <label htmlFor="lender-draft" className="text-sm font-medium">
            Your request (edit anything in [brackets])
          </label>
          <textarea
            id="lender-draft"
            defaultValue={draft.draft}
            rows={9}
            className="w-full rounded-md border bg-background p-3 text-base sm:text-sm"
          />
          <p className="text-xs text-muted-foreground">
            Review it, then send it through {loan.lender}&apos;s website or read
            it on the phone.
          </p>
        </CardContent>
      ) : null}
      <CardFooter className="mt-auto flex flex-wrap justify-center gap-2">
        {draft ? (
          <Button onClick={copy} className={ACTION_BUTTON}>
            {copied ? (
              <Check className="h-4 w-4" aria-hidden="true" />
            ) : (
              <Copy className="h-4 w-4" aria-hidden="true" />
            )}
            {copied ? "Copied" : "Copy request"}
          </Button>
        ) : (
          <Button onClick={negotiate} disabled={busy} className={ACTION_BUTTON}>
            {busy ? "Equa is writing…" : "Negotiate Rate with AI"}
          </Button>
        )}
        {error ? (
          <p role="status" className="w-full text-sm text-muted-foreground">
            {error}
          </p>
        ) : null}
      </CardFooter>
    </Card>
  );
}

function GrantCard({ data }: { data: AprImpact }) {
  const loan = data.highest;
  const plan = data.payoff_with_utility_help;
  const program = data.utility_program;
  if (!loan || !plan) return null;
  return (
    <Card data-apr-animate className="flex flex-col">
      <CardHeader className="flex-col items-center gap-3 space-y-0 text-center">
        <span className={ICON_CHIP}>
          <Zap className="h-5 w-5" aria-hidden="true" />
        </span>
        <div className="grid gap-1">
          <CardTitle className="text-lg">
            {program
              ? `${program.program.name} could speed this up`
              : "Free up money for this loan"}
          </CardTitle>
          <CardDescription>
            {program
              ? "You may qualify for help with your utility bills. "
              : "Help with utility bills could free up cash. "}
            If it covers your {dollars(plan.extra_monthly)} a month in utilities
            and you put that money toward your {loan.lender} loan, you&apos;d
            pay it off{" "}
            <span className="font-semibold text-foreground">
              {plan.months_sooner} months sooner
            </span>{" "}
            and save about{" "}
            <span className="font-semibold text-foreground">
              {dollars(plan.interest_saved)}
            </span>{" "}
            in interest.
          </CardDescription>
        </div>
      </CardHeader>
      <CardFooter className="mt-auto justify-center text-center">
        {program?.application_url ? (
          <Button asChild className={ACTION_BUTTON}>
            <a
              href={program.application_url}
              target="_blank"
              rel="noopener noreferrer"
            >
              Claim Grant &amp; Crush Debt
              <ExternalLink className="h-4 w-4" aria-hidden="true" />
              <span className="sr-only">(opens in a new tab)</span>
            </a>
          </Button>
        ) : (
          <p className="text-sm text-muted-foreground">
            Check the Programs tab for help Equa found for you.
          </p>
        )}
      </CardFooter>
    </Card>
  );
}

export function AprDashboard() {
  const root = useRef<HTMLDivElement>(null);
  const { result } = useCached(CACHE_KEYS.aprImpact, fetchAprImpact);
  const state: State = !result
    ? { kind: "loading" }
    : "data" in result
      ? { kind: "ready", data: result.data }
      : "notConnected" in result
        ? { kind: "not-connected" }
        : { kind: "error", message: result.message };

  // Staggered fade-up once the data is in: the hero metric, then the Magic Cards.
  useGSAP(
    () => {
      if (state.kind !== "ready") return;
      const mm = gsap.matchMedia();
      mm.add("(prefers-reduced-motion: no-preference)", () => {
        gsap.from("[data-apr-animate]", {
          y: 24,
          autoAlpha: 0,
          duration: 0.7,
          ease: "power3.out",
          stagger: 0.15,
        });
      });
    },
    { scope: root, dependencies: [state.kind] },
  );

  if (state.kind === "loading") {
    return (
      <div className="grid animate-pulse gap-4" aria-busy="true">
        <span className="h-40 rounded-2xl bg-muted" />
        <div className="grid gap-4 md:grid-cols-2">
          <span className="h-48 rounded-xl bg-muted" />
          <span className="h-48 rounded-xl bg-muted" />
        </div>
      </div>
    );
  }
  if (state.kind === "not-connected") {
    return (
      <p className="rounded-2xl bg-primary p-6 text-primary-foreground">
        Connect your bank in Settings and Equa will find the interest rates
        costing you the most.
      </p>
    );
  }
  if (state.kind === "error") {
    return <p className="text-sm text-muted-foreground">{state.message}</p>;
  }

  return (
    <div ref={root} className="grid gap-4">
      <AprHero data={state.data} />
      <section
        aria-label="Equa's suggestions"
        className="grid gap-4 md:grid-cols-2"
      >
        <LenderCard data={state.data} />
        <GrantCard data={state.data} />
      </section>
    </div>
  );
}
