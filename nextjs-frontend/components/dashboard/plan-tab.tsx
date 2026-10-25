"use client";

import { useCallback, useRef, useState } from "react";
import gsap from "gsap";
import { useGSAP } from "@gsap/react";
import {
  CheckCircle2,
  ExternalLink,
  Plus,
  Trash2,
  Undo2,
  X,
} from "lucide-react";

import type { AprImpact, ProgramMatches as Matches } from "@/app/clientService";
import {
  fetchAprImpact,
  fetchProgramMatches,
  setApplicationStatus,
} from "@/components/actions/finance-action";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { CACHE_KEYS, peekCached, setCached, useCached } from "@/lib/data-cache";
import { cn } from "@/lib/utils";

gsap.registerPlugin(useGSAP);

export type PlanStep = {
  id: string;
  title: string;
  impact: string;
  /** Added by the user rather than suggested by Equa. */
  own?: boolean;
  /** Where to act on this step, e.g. the program's application page. */
  link?: { href: string; label: string };
  /** For "Apply for …" steps: completing the step completes that application. */
  programId?: number;
  /** Already finished according to the data (e.g. application marked complete). */
  done?: boolean;
};

type Decision = "approved" | "skipped" | "complete";
type Decisions = Record<string, Decision>;

const money = (n: number) =>
  new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  }).format(Math.round(n));

/**
 * Equa's steps, built from data the dashboard already has (APR impact and program
 * matches), so the plan never contradicts the user's real numbers. Order: free up
 * money first, then lower the cost of debt, then the other help Equa found.
 */
export function buildPlanSteps(
  impact: AprImpact | null,
  matches: Matches | null,
): PlanStep[] {
  const steps: PlanStep[] = [];
  const loan = impact?.highest ?? null;
  const plan = impact?.payoff_with_utility_help ?? null;
  const utility = impact?.utility_program ?? null;

  // The matches list is the freshest status (it's what the Programs tab updates).
  const statusOf = (id: number, fallback: string) =>
    matches?.matches.find((m) => m.program.id === id)?.application_status ??
    fallback;

  // A program the user said doesn't apply to them has no place in the plan.
  if (
    utility &&
    statusOf(utility.program.id, utility.application_status) !==
      "not-applicable"
  ) {
    steps.push({
      id: `program-${utility.program.id}`,
      programId: utility.program.id,
      done:
        statusOf(utility.program.id, utility.application_status) === "complete",
      title: `Apply for ${utility.program.name}.`,
      impact:
        plan && loan
          ? `You may qualify for help with your ${money(plan.extra_monthly)} a month in utilities. Put that toward your ${loan.lender} loan and you'd finish it ${plan.months_sooner} months sooner, saving about ${money(plan.interest_saved)}.`
          : utility.reason,
      link: utility.application_url
        ? { href: utility.application_url, label: "Open application" }
        : undefined,
    });
  }
  if (loan) {
    steps.push({
      id: "lender-rate",
      title: `Ask ${loan.lender} for a lower rate.`,
      impact: `Your ${loan.apr}% APR costs about ${money(loan.monthly_interest)} a month in interest. Equa can write the request for you on the Overview tab.`,
    });
  }
  for (const m of matches?.matches ?? []) {
    if (m.program.id === utility?.program.id) continue; // already step 1
    if (m.application_status === "not-applicable") continue;
    steps.push({
      id: `program-${m.program.id}`,
      programId: m.program.id,
      done: m.application_status === "complete",
      title: `Apply for ${m.program.name}.`,
      impact: m.reason,
      link: m.application_url
        ? { href: m.application_url, label: "Open application" }
        : undefined,
    });
  }
  return steps;
}

/** A value kept in the dashboard cache, so it survives switching tabs. */
function useCachedState<T>(key: string, initial: T) {
  const [value, setValue] = useState<T>(() => peekCached<T>(key) ?? initial);
  const update = useCallback(
    (next: T) => {
      setCached<T>(key, () => next);
      setValue(next);
    },
    [key],
  );
  return [value, update] as const;
}

function AddTaskForm({
  onAdd,
  onCancel,
}: {
  onAdd: (step: PlanStep) => void;
  onCancel: () => void;
}) {
  const formRef = useRef<HTMLFormElement>(null);
  const [title, setTitle] = useState("");
  const [impact, setImpact] = useState("");

  // Pops up out of the + button.
  useGSAP(
    () => {
      const mm = gsap.matchMedia();
      mm.add("(prefers-reduced-motion: no-preference)", () => {
        gsap.from(formRef.current, {
          y: 16,
          scale: 0.96,
          autoAlpha: 0,
          duration: 0.3,
          ease: "power2.out",
          clearProps: "transform,opacity,visibility",
        });
      });
    },
    { scope: formRef },
  );

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!title.trim()) return;
    onAdd({
      id: `own-${Date.now()}`,
      title: title.trim(),
      impact: impact.trim(),
      own: true,
    });
    setTitle("");
    setImpact("");
  };

  return (
    <form
      id="plan-add-form"
      ref={formRef}
      onSubmit={submit}
      onKeyDown={(e) => {
        if (e.key === "Escape") onCancel();
      }}
      className="grid w-full gap-3 rounded-lg border bg-card p-4 shadow-sm"
    >
      <div className="grid gap-2">
        <Label htmlFor="plan-task">Add your own task</Label>
        <Input
          id="plan-task"
          autoFocus
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="Call the electric company about a payment plan"
          maxLength={120}
          className="h-11 text-base sm:text-sm"
        />
      </div>
      <div className="grid gap-2">
        <Label htmlFor="plan-impact">
          How it helps <span className="text-muted-foreground">(optional)</span>
        </Label>
        <Input
          id="plan-impact"
          value={impact}
          onChange={(e) => setImpact(e.target.value)}
          placeholder="Spreads this month's bill over 3 months"
          maxLength={160}
          className="h-11 text-base sm:text-sm"
        />
      </div>
      <Button
        type="submit"
        disabled={!title.trim()}
        className="min-h-11 sm:w-fit"
      >
        <Plus className="h-4 w-4" aria-hidden="true" />
        Add to my plan
      </Button>
    </form>
  );
}

/** A big round + button that opens the add-task form beneath it. */
function AddTaskButton({ onAdd }: { onAdd: (step: PlanStep) => void }) {
  const [open, setOpen] = useState(false);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const close = () => {
    setOpen(false);
    buttonRef.current?.focus();
  };

  return (
    <div className="flex flex-col items-center gap-4">
      <button
        ref={buttonRef}
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        aria-controls="plan-add-form"
        aria-label={open ? "Close the add task form" : "Add your own task"}
        title={open ? "Close" : "Add your own task"}
        className="flex h-16 w-16 items-center justify-center rounded-full bg-primary text-primary-foreground shadow-lg transition-transform hover:scale-105 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 active:scale-95 motion-reduce:transition-none"
      >
        <Plus
          aria-hidden="true"
          className={cn(
            "h-8 w-8 transition-transform duration-200 motion-reduce:transition-none",
            open && "rotate-45", // the + turns into an x
          )}
        />
      </button>
      {open ? (
        <AddTaskForm
          onAdd={(step) => {
            onAdd(step);
            close();
          }}
          onCancel={close}
        />
      ) : null}
    </div>
  );
}

/** Finished steps, in a drawer that slides in from the right. Closed by default. */
function CompletedDrawer({
  steps,
  onReopen,
}: {
  steps: PlanStep[];
  onReopen: (step: PlanStep) => void;
}) {
  const [open, setOpen] = useState(false);
  const openButton = useRef<HTMLButtonElement>(null);
  const closeButton = useRef<HTMLButtonElement>(null);

  const close = () => {
    setOpen(false);
    openButton.current?.focus();
  };

  return (
    <>
      <Button
        ref={openButton}
        variant="outline"
        className="min-h-11 shrink-0"
        aria-expanded={open}
        aria-controls="plan-completed"
        onClick={() => {
          setOpen(true);
          requestAnimationFrame(() => closeButton.current?.focus());
        }}
      >
        <CheckCircle2 className="h-4 w-4" aria-hidden="true" />
        Completed ({steps.length})
      </Button>

      <div
        aria-hidden="true"
        onClick={close}
        className={cn(
          "fixed inset-0 z-40 bg-black/40 transition-opacity duration-200 motion-reduce:transition-none",
          open ? "opacity-100" : "pointer-events-none opacity-0",
        )}
      />
      <aside
        id="plan-completed"
        role="dialog"
        aria-modal="true"
        aria-labelledby="plan-completed-heading"
        onKeyDown={(e) => {
          if (e.key === "Escape") close();
        }}
        className={cn(
          "fixed inset-y-0 right-0 z-50 flex w-80 max-w-[85vw] flex-col border-l bg-background shadow-xl transition-[transform,visibility] duration-300 ease-out motion-reduce:transition-none",
          open ? "visible translate-x-0" : "invisible translate-x-full",
        )}
      >
        <div className="flex items-center justify-between gap-2 border-b px-4 py-2">
          <h3 id="plan-completed-heading" className="font-semibold">
            Completed ({steps.length})
          </h3>
          <button
            ref={closeButton}
            type="button"
            onClick={close}
            aria-label="Close completed steps"
            className="inline-flex h-11 w-11 items-center justify-center rounded-md text-muted-foreground hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <X className="h-5 w-5" aria-hidden="true" />
          </button>
        </div>
        {steps.length ? (
          <ul className="grid gap-3 overflow-y-auto p-4">
            {steps.map((step) => (
              <li
                key={step.id}
                className="grid gap-2 rounded-lg border bg-card p-3"
              >
                <p className="flex items-start gap-2 text-sm font-semibold">
                  <CheckCircle2
                    className="mt-0.5 h-4 w-4 shrink-0"
                    aria-hidden="true"
                  />
                  <span className="min-w-0 break-words">{step.title}</span>
                </p>
                {step.own ? (
                  <p className="text-xs text-muted-foreground">Added by you</p>
                ) : null}
                <Button
                  variant="ghost"
                  size="sm"
                  className="min-h-11 w-fit"
                  onClick={() => onReopen(step)}
                >
                  <Undo2 className="h-4 w-4" aria-hidden="true" />
                  Move back to my plan
                </Button>
              </li>
            ))}
          </ul>
        ) : (
          <p className="p-4 text-sm text-muted-foreground">
            Nothing here yet. Finished steps will show up here.
          </p>
        )}
      </aside>
    </>
  );
}

export function PlanTab({
  steps: stepsOverride,
  onApprove,
  onReject,
}: {
  /** Use these steps instead of building them from the user's data. */
  steps?: PlanStep[];
  /** Hook for the AI: called when a step is approved. */
  onApprove?: (step: PlanStep) => void;
  /** Hook for the AI: called when a step is rejected, so it can recalculate. */
  onReject?: (step: PlanStep) => void;
}) {
  const listRef = useRef<HTMLOListElement>(null);
  const [decisions, setDecisions] = useCachedState<Decisions>(
    CACHE_KEYS.planDecisions,
    {},
  );
  const [ownSteps, setOwnSteps] = useCachedState<PlanStep[]>(
    CACHE_KEYS.planOwnSteps,
    [],
  );
  const [active, setActive] = useState(0);

  // Same cache keys as Overview and Programs: no extra server calls.
  const apr = useCached(CACHE_KEYS.aprImpact, fetchAprImpact);
  const programs = useCached(CACHE_KEYS.programMatches, () =>
    fetchProgramMatches(),
  );
  const notConnected = [apr.result, programs.result].some(
    (r) => r && "notConnected" in r,
  );
  const ready = !apr.loading && !programs.loading;
  const steps =
    stepsOverride ??
    buildPlanSteps(
      apr.result && "data" in apr.result ? apr.result.data : null,
      programs.result && "data" in programs.result
        ? programs.result.data
        : null,
    );
  // Program steps follow the saved application status (shared with the Programs
  // tab); only the user's own tasks use the local decision.
  const isComplete = (step: PlanStep) =>
    step.programId ? Boolean(step.done) : decisions[step.id] === "complete";
  const everyStep = [...steps, ...ownSteps];
  const allSteps = everyStep.filter((s) => !isComplete(s));
  const completedSteps = everyStep.filter(isComplete);

  // Keep the Programs tab in step: completing or dismissing "Apply for X" does
  // the same to X there, and the step leaves the plan.
  type MatchesResult = Awaited<ReturnType<typeof fetchProgramMatches>>;
  type AppStatus = Parameters<typeof setApplicationStatus>[1];
  const syncApplication = async (programId: number, status: AppStatus) => {
    const current = peekCached<MatchesResult>(CACHE_KEYS.programMatches);
    const previous =
      (current &&
        "data" in current &&
        current.data.matches.find((m) => m.program.id === programId)
          ?.application_status) ||
      "in-progress";
    const flip = (to: AppStatus) =>
      setCached<MatchesResult>(CACHE_KEYS.programMatches, (prev) =>
        prev && "data" in prev
          ? {
              data: {
                ...prev.data,
                matches: prev.data.matches.map((m) =>
                  m.program.id === programId
                    ? { ...m, application_status: to }
                    : m,
                ),
              },
            }
          : (prev as MatchesResult),
      );
    flip(status);
    const saved = await setApplicationStatus(programId, status);
    if (!("ok" in saved)) flip(previous);
  };

  const dismissStep = (step: PlanStep) => {
    setActive((i) => Math.max(0, Math.min(i, allSteps.length - 2)));
    if (step.programId) void syncApplication(step.programId, "not-applicable");
  };

  const completeStep = (step: PlanStep) => {
    decide(step, "complete");
    setActive((i) => Math.max(0, Math.min(i, allSteps.length - 2)));
    if (step.programId) void syncApplication(step.programId, "complete");
  };

  const reopenStep = (step: PlanStep) => {
    decide(step, "approved");
    if (step.programId) void syncApplication(step.programId, "in-progress");
  };

  const decide = (step: PlanStep, decision: Decision | null) => {
    const next = { ...decisions };
    if (decision) next[step.id] = decision;
    else delete next[step.id];
    setDecisions(next);
    if (decision === "approved") onApprove?.(step);
    if (decision === "skipped") onReject?.(step);
  };

  const addStep = (step: PlanStep) => {
    setOwnSteps([...ownSteps, step]);
    // Bring the new task into focus once it's rendered.
    requestAnimationFrame(() => focusStep(allSteps.length));
  };

  const removeStep = (step: PlanStep) => {
    setOwnSteps(ownSteps.filter((s) => s.id !== step.id));
    setActive((i) => Math.min(i, allSteps.length - 2));
  };

  // The card nearest the top of the list is "in focus": full size and opacity.
  const onScroll = () => {
    const list = listRef.current;
    if (!list) return;
    const top = list.getBoundingClientRect().top;
    let best = 0;
    let bestDistance = Infinity;
    Array.from(list.children).forEach((child, i) => {
      const distance = Math.abs(child.getBoundingClientRect().top - top);
      if (distance < bestDistance) {
        bestDistance = distance;
        best = i;
      }
    });
    setActive(best);
  };

  const focusStep = (index: number) => {
    const card = listRef.current?.children[index] as HTMLElement | undefined;
    card?.scrollIntoView({ behavior: "smooth", block: "start" });
    setActive(index);
  };

  // Steps slide up one after another, like Equa laying out the plan.
  useGSAP(
    () => {
      const mm = gsap.matchMedia();
      mm.add("(prefers-reduced-motion: no-preference)", () => {
        gsap.from("[data-plan-step]", {
          y: 40,
          autoAlpha: 0,
          duration: 0.6,
          ease: "power3.out",
          stagger: 0.2,
          // Hand opacity and size back to the focus styles when done.
          clearProps: "transform,opacity,visibility",
        });
      });
    },
    // Replays once Equa's steps arrive, so they slide in as they're laid out.
    { scope: listRef, dependencies: [ready] },
  );

  return (
    <section aria-labelledby="plan-heading" className="grid max-w-2xl gap-6">
      <div>
        <div className="flex flex-wrap items-start justify-between gap-2">
          <h2 id="plan-heading" className="text-lg font-semibold">
            Your plan, one step at a time
          </h2>
          <CompletedDrawer steps={completedSteps} onReopen={reopenStep} />
        </div>
        <p className="text-sm text-muted-foreground">
          Here&apos;s a calm path forward. Scroll to move through it, and tell
          Equa if a step doesn&apos;t work for you.
        </p>
        {!stepsOverride && !ready ? (
          <p
            role="status"
            className="mt-2 animate-pulse text-sm text-muted-foreground"
          >
            Equa is putting your plan together…
          </p>
        ) : notConnected ? (
          <p className="mt-2 text-sm text-muted-foreground">
            Connect your bank in Settings and Equa will build your plan. You can
            add your own tasks below in the meantime.
          </p>
        ) : null}
      </div>

      {/* Rotating list: cards snap to the top, the one in focus is full size. The
          bottom padding lets the last card reach the top too. */}
      <ol
        ref={listRef}
        onScroll={onScroll}
        aria-label="Plan steps"
        className="grid max-h-[65vh] snap-y snap-mandatory gap-4 overflow-y-auto overscroll-contain pb-[45vh] pr-1"
      >
        {allSteps.map((step, i) => {
          const decision = decisions[step.id];
          const focused = i === active;
          return (
            <li
              key={step.id}
              data-plan-step
              className={cn(
                "snap-start transition-[transform,opacity] duration-300 ease-out motion-reduce:transition-none",
                focused ? "scale-100 opacity-100" : "scale-[0.92] opacity-50",
              )}
              // A faded card can be tapped to bring it into focus.
              onClick={focused ? undefined : () => focusStep(i)}
              onFocusCapture={focused ? undefined : () => focusStep(i)}
            >
              <Card
                className={cn(
                  "transition-shadow",
                  focused ? "shadow-md" : "cursor-pointer shadow-none",
                  decision === "skipped" && "opacity-60",
                )}
              >
                <CardHeader className="flex-row items-start gap-3 space-y-0 pb-2">
                  <span
                    aria-hidden="true"
                    className={cn(
                      "flex h-10 w-10 shrink-0 items-center justify-center rounded-full border-2 text-sm font-bold",
                      decision === "approved"
                        ? "border-primary bg-primary text-primary-foreground"
                        : "border-border bg-background text-foreground",
                    )}
                  >
                    {decision === "approved" ? (
                      <CheckCircle2 className="h-5 w-5" />
                    ) : (
                      i + 1
                    )}
                  </span>
                  <div className="grid min-w-0 flex-1 gap-1">
                    <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                      Step {i + 1}
                      {step.own ? " · Added by you" : ""}
                    </p>
                    <CardTitle
                      className={cn(
                        "break-words leading-snug",
                        focused ? "text-xl" : "text-lg",
                      )}
                    >
                      {step.title}
                    </CardTitle>
                  </div>
                </CardHeader>
                {step.impact ? (
                  <CardContent className="pb-4">
                    <p className="text-sm text-muted-foreground">
                      {step.impact}
                    </p>
                  </CardContent>
                ) : null}
                <CardFooter className="flex flex-wrap gap-2">
                  {decision === "approved" ? (
                    <>
                      <p role="status" className="w-full text-sm font-medium">
                        Great, this step is on your list.
                      </p>
                      <Button
                        className="min-h-11 w-full sm:w-auto"
                        onClick={() => completeStep(step)}
                      >
                        <CheckCircle2 className="h-4 w-4" aria-hidden="true" />
                        Mark complete
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        className="min-h-11"
                        onClick={() => decide(step, null)}
                      >
                        <Undo2 className="h-4 w-4" aria-hidden="true" />
                        Undo
                      </Button>
                    </>
                  ) : decision === "skipped" ? (
                    <>
                      <p role="status" className="flex-1 text-sm font-medium">
                        Got it. Equa will skip this step for now.
                      </p>
                      <Button
                        variant="ghost"
                        size="sm"
                        className="min-h-11"
                        onClick={() => decide(step, null)}
                      >
                        <Undo2 className="h-4 w-4" aria-hidden="true" />
                        Undo
                      </Button>
                    </>
                  ) : (
                    <>
                      <Button
                        className="min-h-11 w-full sm:w-auto"
                        onClick={() => decide(step, "approved")}
                      >
                        Looks good, let&apos;s do this.
                      </Button>
                      {step.programId ? (
                        <Button
                          variant="ghost"
                          className="min-h-11 w-full sm:w-auto"
                          onClick={() => dismissStep(step)}
                        >
                          This doesn&apos;t apply to me.
                        </Button>
                      ) : (
                        <Button
                          variant="ghost"
                          className="min-h-11 w-full sm:w-auto"
                          onClick={() => decide(step, "skipped")}
                        >
                          This isn&apos;t realistic right now.
                        </Button>
                      )}
                    </>
                  )}
                  {step.link ? (
                    <Button
                      asChild
                      variant="outline"
                      className="min-h-11 w-full sm:w-auto"
                    >
                      <a
                        href={step.link.href}
                        target="_blank"
                        rel="noopener noreferrer"
                      >
                        {step.link.label}
                        <ExternalLink className="h-4 w-4" aria-hidden="true" />
                        <span className="sr-only">(opens in a new tab)</span>
                      </a>
                    </Button>
                  ) : null}
                  {step.own ? (
                    <Button
                      variant="ghost"
                      size="sm"
                      className="min-h-11"
                      onClick={() => removeStep(step)}
                      aria-label={`Remove "${step.title}"`}
                    >
                      <Trash2 className="h-4 w-4" aria-hidden="true" />
                      Remove
                    </Button>
                  ) : null}
                </CardFooter>
              </Card>
            </li>
          );
        })}
      </ol>

      <AddTaskButton onAdd={addStep} />
    </section>
  );
}
