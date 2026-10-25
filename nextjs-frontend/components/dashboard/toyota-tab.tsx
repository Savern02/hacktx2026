"use client";

import { useRef, useState } from "react";
import gsap from "gsap";
import { useGSAP } from "@gsap/react";
import {
  HeartHandshake,
  CalendarClock,
  Car,
  Check,
  Copy,
  ExternalLink,
  CalendarRange,
  Phone,
  Repeat,
  ShieldCheck,
} from "lucide-react";

import type { LenderRequest } from "@/app/clientService";
import { fetchBalance } from "@/components/actions/balance-action";
import {
  draftLenderRequest,
  fetchAprImpact,
  fetchFinancialHealth,
} from "@/components/actions/finance-action";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { CACHE_KEYS, peekCached, setCached, useCached } from "@/lib/data-cache";
import { useFirstName } from "@/lib/use-first-name";

gsap.registerPlugin(useGSAP);

// Real Toyota Financial Services (TFS) pages and options, checked Oct 2026.
const TFS_PHONE = "800-874-8822";
const TFS_DEFERRAL_FAQ =
  "https://www.toyotafinancial.com/us/en/planning_tools/faq/extension_and_deferral/what_is_a_deferral_and_does_tfs_offer_deferrals.html";
const TFS_DUE_DATE_CHANGE =
  "https://support.toyotafinancial.com/s/tfs-due-date-change";
const SMARTPATH = "https://www.toyota.com/smartpath";
// A common guideline (the "20/4/10" rule): keep car payments around 10% of income.
const CAR_COST_GUIDELINE = 0.1;

const money = (n: number) =>
  new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  }).format(Math.round(n));

const shortDate = new Intl.DateTimeFormat("en-US", {
  month: "short",
  day: "numeric",
  timeZone: "UTC",
});

function daysUntil(isoDate: string): number {
  const due = new Date(isoDate + "T00:00:00Z").getTime();
  const today = new Date(
    new Date().toISOString().slice(0, 10) + "T00:00:00Z",
  ).getTime();
  return Math.round((due - today) / 86_400_000);
}

function DeferRequestCard() {
  const [draft, setDraftState] = useState<LenderRequest | null>(
    () => peekCached<LenderRequest>(CACHE_KEYS.deferRequest) ?? null,
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const draftIt = async () => {
    setBusy(true);
    setError(null);
    const result = await draftLenderRequest("deferment");
    setBusy(false);
    if ("data" in result) {
      setCached<LenderRequest>(CACHE_KEYS.deferRequest, () => result.data);
      setDraftState(result.data);
    } else {
      setError(result.message);
    }
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
    <Card data-toyota-animate className="flex flex-col">
      <CardHeader className="flex-col items-center gap-3 space-y-0 text-center">
        <span className="flex h-10 w-10 items-center justify-center rounded-full bg-muted">
          <CalendarClock className="h-5 w-5" aria-hidden="true" />
        </span>
        <div className="grid gap-1">
          <CardTitle className="text-lg">
            Ask TFS for a payment extension
          </CardTitle>
          <CardDescription>
            Tight months happen. For a temporary hardship, Toyota Financial
            Services can move a payment to the end of your loan. They review
            each request and it may add charges, so Equa writes the request and
            asks those questions for you.
          </CardDescription>
        </div>
      </CardHeader>
      {draft ? (
        <CardContent className="grid gap-2">
          <label htmlFor="defer-draft" className="text-sm font-medium">
            Your request (edit anything in [brackets])
          </label>
          <textarea
            id="defer-draft"
            defaultValue={draft.draft}
            rows={9}
            className="w-full rounded-md border bg-background p-3 text-left text-base sm:text-sm"
          />
          <p className="text-xs text-muted-foreground">
            Send it from the Mail Center in your TFS account, or read it when
            you call.
          </p>
        </CardContent>
      ) : null}
      <CardFooter className="mt-auto flex flex-wrap justify-center gap-2">
        {draft ? (
          <Button onClick={copy} className="min-h-11 w-full sm:w-auto">
            {copied ? (
              <Check className="h-4 w-4" aria-hidden="true" />
            ) : (
              <Copy className="h-4 w-4" aria-hidden="true" />
            )}
            {copied ? "Copied" : "Copy request"}
          </Button>
        ) : (
          <Button
            variant="outline"
            onClick={draftIt}
            disabled={busy}
            className="min-h-11 w-full sm:w-auto"
          >
            {busy ? "Equa is writing…" : "Write my request"}
          </Button>
        )}
        <Button asChild variant="ghost" className="min-h-11 w-full sm:w-auto">
          <a href={`tel:${TFS_PHONE}`}>
            <Phone className="h-4 w-4" aria-hidden="true" />
            Call TFS {TFS_PHONE}
          </a>
        </Button>
        <a
          href={TFS_DEFERRAL_FAQ}
          target="_blank"
          rel="noopener noreferrer"
          className="w-full text-xs text-muted-foreground underline underline-offset-4 hover:text-foreground"
        >
          How TFS deferrals work
          <span className="sr-only"> (opens in a new tab)</span>
        </a>
        {error ? (
          <p role="status" className="w-full text-sm text-muted-foreground">
            {error}
          </p>
        ) : null}
      </CardFooter>
    </Card>
  );
}

function DueDateCard({ dueDay }: { dueDay: number | null }) {
  return (
    <Card data-toyota-animate className="flex flex-col">
      <CardHeader className="flex-col items-center gap-3 space-y-0 text-center">
        <span className="flex h-10 w-10 items-center justify-center rounded-full bg-muted">
          <CalendarRange className="h-5 w-5" aria-hidden="true" />
        </span>
        <div className="grid gap-1">
          <CardTitle className="text-lg">
            Move your due date to payday
          </CardTitle>
          <CardDescription>
            {dueDay !== null
              ? `Your payment is due on the ${ordinal(dueDay)}. `
              : ""}
            If that lands before your paycheck, you can ask TFS for a new due
            date online. A TFS representative reviews it and replies in your
            account. Finance accounts can pick any day except the 31st.
          </CardDescription>
        </div>
      </CardHeader>
      <CardFooter className="mt-auto flex flex-wrap justify-center gap-2">
        <Button asChild variant="outline" className="min-h-11 w-full sm:w-auto">
          <a
            href={TFS_DUE_DATE_CHANGE}
            target="_blank"
            rel="noopener noreferrer"
          >
            Request a new due date
            <ExternalLink className="h-4 w-4" aria-hidden="true" />
            <span className="sr-only">(opens in a new tab)</span>
          </a>
        </Button>
      </CardFooter>
    </Card>
  );
}

function ordinal(n: number): string {
  const s =
    n % 100 >= 11 && n % 100 <= 13
      ? "th"
      : (["th", "st", "nd", "rd"][n % 10] ?? "th");
  return `${n}${s}`;
}

function TradeDownCard({
  payment,
  income,
}: {
  payment: number;
  income: number | null;
}) {
  const target = income ? income * CAR_COST_GUIDELINE : null;
  const share = income ? Math.round((payment / income) * 100) : null;
  const savings = target !== null ? payment - target : null;
  const helps = savings !== null && savings > 0;

  return (
    <Card data-toyota-animate className="flex flex-col md:col-span-2">
      <CardHeader className="flex-col items-center gap-3 space-y-0 text-center">
        <div className="flex flex-wrap justify-center gap-2">
          {helps ? <Badge>Recommended</Badge> : null}
          {/* Equa has no SmartPath connection: this is an illustration, not a quote. */}
          <Badge variant="outline">Concept</Badge>
        </div>
        <span className="flex h-10 w-10 items-center justify-center rounded-full bg-muted">
          <Repeat className="h-5 w-5" aria-hidden="true" />
        </span>
        <div className="grid gap-1">
          <CardTitle className="text-lg">
            Right-size your ride with SmartPath
          </CardTitle>
          <CardDescription>
            {share !== null
              ? `This payment takes up ${share}% of your monthly budget. `
              : ""}
            Toyota SmartPath gives you an instant trade-in estimate and payment
            estimates online, and saves your progress in a digital garage so you
            can finish at a participating dealer. A lower-priced Toyota could
            free up cash every month.
          </CardDescription>
        </div>
      </CardHeader>
      <CardContent>
        {/* The example uses only the user's own numbers and a common guideline. */}
        <dl className="grid gap-2 rounded-lg border bg-muted/40 p-4 text-sm">
          <div className="flex items-center justify-between gap-3">
            <dt className="text-muted-foreground">Your payment now</dt>
            <dd className="font-semibold tabular-nums">{money(payment)}/mo</dd>
          </div>
          {target !== null ? (
            <div className="flex items-center justify-between gap-3">
              <dt className="text-muted-foreground">At 10% of your income</dt>
              <dd className="font-semibold tabular-nums">
                about {money(target)}/mo
              </dd>
            </div>
          ) : null}
          {helps ? (
            <div className="flex items-center justify-between gap-3 border-t pt-2">
              <dt className="font-medium">Frees up in cash flow</dt>
              <dd className="font-bold tabular-nums">
                about {money(savings)}/mo
              </dd>
            </div>
          ) : null}
          <p className="flex items-start gap-2 border-t pt-2 text-left text-xs text-muted-foreground">
            <ShieldCheck
              className="mt-0.5 h-4 w-4 shrink-0"
              aria-hidden="true"
            />
            {helps
              ? "An example based on your income, not a quote. Your dealer and Toyota Financial Services set the real price, trade-in value and payment."
              : "Your payment is already within the 10% guideline, so a trade-down isn't needed."}
          </p>
        </dl>
      </CardContent>
      <CardFooter className="mt-auto flex flex-wrap justify-center gap-2">
        <Button asChild className="min-h-11 w-full sm:w-auto">
          <a href={SMARTPATH} target="_blank" rel="noopener noreferrer">
            Value my trade-in on SmartPath
            <ExternalLink className="h-4 w-4" aria-hidden="true" />
            <span className="sr-only">(opens in a new tab)</span>
          </a>
        </Button>
      </CardFooter>
    </Card>
  );
}

export function ToyotaTab() {
  const root = useRef<HTMLDivElement>(null);
  const firstName = useFirstName();
  // Same cache keys as Overview: opening this tab costs no extra requests.
  const apr = useCached(CACHE_KEYS.aprImpact, fetchAprImpact);
  const balance = useCached(CACHE_KEYS.balance, fetchBalance);
  const health = useCached(CACHE_KEYS.health, fetchFinancialHealth);

  const ready = !apr.loading && !balance.loading && !health.loading;
  const notConnected = [apr.result, balance.result, health.result].some(
    (r) => r && "notConnected" in r,
  );
  const loans = apr.result && "data" in apr.result ? apr.result.data.loans : [];
  const loan = loans.find((l) => /toyota/i.test(`${l.lender} ${l.name}`));
  const bank =
    balance.result && "data" in balance.result ? balance.result.data : null;
  const income =
    health.result && "data" in health.result
      ? health.result.data.income_monthly
      : null;
  const bill = loan && bank?.upcoming_bills.find((b) => b.name === loan.name);
  const days = bill ? daysUntil(bill.due_date) : null;

  useGSAP(
    () => {
      if (!ready) return;
      const mm = gsap.matchMedia();
      mm.add("(prefers-reduced-motion: no-preference)", () => {
        gsap.from("[data-toyota-animate]", {
          y: 24,
          autoAlpha: 0,
          duration: 0.6,
          ease: "power3.out",
          stagger: 0.15,
          clearProps: "transform,opacity,visibility",
        });
      });
    },
    { scope: root, dependencies: [ready] },
  );

  if (!ready) {
    return (
      <div
        className="mx-auto grid w-full max-w-3xl animate-pulse gap-4"
        aria-busy="true"
      >
        <span className="h-44 rounded-2xl bg-muted" />
        <div className="grid gap-4 md:grid-cols-2">
          <span className="h-64 rounded-xl bg-muted" />
          <span className="h-64 rounded-xl bg-muted" />
        </div>
      </div>
    );
  }
  if (notConnected) {
    return (
      <p className="mx-auto max-w-md text-center text-sm text-muted-foreground">
        Connect your bank in Settings and Equa will look at your Toyota loan.
      </p>
    );
  }
  if (!loan) {
    return (
      <p className="mx-auto max-w-md text-center text-sm text-muted-foreground">
        Equa doesn&apos;t see a Toyota loan on your account.
      </p>
    );
  }

  // Calm, factual alert from the real balance and bills. No red, no panic.
  const covers = bank ? bank.balance >= loan.monthly_payment : null;
  const shortOverall = bank && bank.safe_to_spend < 0 ? -bank.safe_to_spend : 0;
  const alert = !bank
    ? null
    : !covers
      ? `Your safe balance (${money(bank.balance)}) is a bit short for this ${money(loan.monthly_payment)} payment. Let's protect your credit and look at some options together.`
      : shortOverall > 0
        ? `Your balance covers this payment, but you're about ${money(shortOverall)} short across this month's bills. Let's protect your credit and look at some options together.`
        : `You're covered for this payment. Nice work${firstName ? `, ${firstName}` : ""}!`;

  return (
    <div ref={root} className="mx-auto grid w-full max-w-3xl gap-6 text-center">
      <section
        data-toyota-animate
        aria-labelledby="toyota-heading"
        className="grid justify-items-center gap-3 rounded-2xl bg-primary p-6 text-primary-foreground sm:p-8"
      >
        <span className="flex h-12 w-12 items-center justify-center rounded-full bg-primary-foreground/10">
          <Car className="h-6 w-6" aria-hidden="true" />
        </span>
        <p className="text-sm text-primary-foreground/70">Your Toyota loan</p>
        <h2 id="toyota-heading" className="text-2xl font-bold">
          {loan.name}
        </h2>
        <p className="text-lg">
          <span className="font-semibold">{money(loan.monthly_payment)}</span> a
          month
          {bill && days !== null
            ? ` · due ${days <= 0 ? "today" : `in ${days} day${days === 1 ? "" : "s"}`} (${shortDate.format(new Date(bill.due_date))})`
            : ""}
        </p>
        <p className="text-xs text-primary-foreground/70">
          {loan.apr}% APR · {loan.apr_basis}
        </p>
        {alert ? (
          <p
            role="status"
            className="mt-2 flex max-w-md items-start gap-2 rounded-lg bg-primary-foreground/10 px-4 py-3 text-left text-sm"
          >
            <HeartHandshake
              className="mt-0.5 h-4 w-4 shrink-0"
              aria-hidden="true"
            />
            <span>
              <span className="font-semibold">Cash flow update: </span>
              {alert}
            </span>
          </p>
        ) : null}
      </section>

      <section aria-labelledby="toyota-moves" className="grid gap-4">
        <h2
          id="toyota-moves"
          data-toyota-animate
          className="text-lg font-semibold"
        >
          Equa&apos;s proactive solutions
        </h2>
        <div className="grid gap-4 md:grid-cols-2">
          <DeferRequestCard />
          <DueDateCard
            dueDay={bill ? new Date(bill.due_date).getUTCDate() : null}
          />
          <TradeDownCard payment={loan.monthly_payment} income={income} />
        </div>
        <p
          data-toyota-animate
          className="mx-auto max-w-md text-xs text-muted-foreground"
        >
          Hit by a hurricane, wildfire or other declared disaster? TFS often
          announces extra payment relief for affected areas. Call{" "}
          <a href={`tel:${TFS_PHONE}`} className="underline underline-offset-4">
            {TFS_PHONE}
          </a>{" "}
          to ask.
        </p>
      </section>
    </div>
  );
}
