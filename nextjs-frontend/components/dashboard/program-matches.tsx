"use client";

import { useRef, useState } from "react";
import { ChevronDown, ExternalLink, Sparkles, Star } from "lucide-react";

import type { ProgramMatches as Matches } from "@/app/clientService";
import {
  fetchProgramMatches,
  setApplicationStatus,
} from "@/components/actions/finance-action";
import { StatusProgressBar } from "@/components/dashboard/status-progress-bar";
import { CACHE_KEYS, invalidate, setCached, useCached } from "@/lib/data-cache";
import { programIcon } from "@/lib/program-icons";
import { cn } from "@/lib/utils";

type State =
  | { kind: "loading" }
  | { kind: "not-connected" }
  | { kind: "error"; message: string }
  | { kind: "ready"; data: Matches };

function toState(
  result: Awaited<ReturnType<typeof fetchProgramMatches>>,
): State {
  if ("data" in result) return { kind: "ready", data: result.data };
  if ("notConnected" in result) return { kind: "not-connected" };
  return { kind: "error", message: result.message };
}

type Match = Matches["matches"][number];
type Status = Match["application_status"];

const BUTTON =
  "min-h-11 rounded-md border px-3 text-sm font-medium hover:bg-accent";

function MatchCard({
  m,
  onSetStatus,
  best = false,
}: {
  m: Match;
  onSetStatus: (programId: number, current: Status, next: Status) => void;
  best?: boolean;
}) {
  const set = (next: Status) =>
    onSetStatus(m.program.id, m.application_status, next);
  return (
    <li
      className={cn(
        "grid gap-3 rounded-lg border bg-card p-4",
        best && "border-primary ring-2 ring-primary md:col-span-2",
      )}
    >
      {best ? (
        <p className="inline-flex w-fit items-center gap-1.5 rounded-full bg-primary px-3 py-1 text-xs font-semibold uppercase tracking-wide text-primary-foreground">
          <Star className="h-3.5 w-3.5 fill-current" aria-hidden="true" />
          Best First Step
        </p>
      ) : null}
      <StatusProgressBar
        status={m.application_status}
        label={m.program.name}
        icon={programIcon(m.program)}
      />
      <p className="text-xs text-muted-foreground">{m.program.jurisdiction}</p>
      <p className="line-clamp-2 min-h-10 text-sm leading-5">{m.reason}</p>
      <div className="flex flex-wrap gap-2">
        {m.application_url && m.application_status === "in-progress" ? (
          <a
            href={m.application_url}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex min-h-11 items-center gap-1.5 rounded-md bg-primary px-3 text-sm font-semibold text-primary-foreground hover:bg-primary/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
          >
            Apply
            <ExternalLink className="h-4 w-4" aria-hidden="true" />
            <span className="sr-only">(opens in a new tab)</span>
          </a>
        ) : null}
        {m.application_status === "in-progress" ? (
          <>
            <button
              type="button"
              onClick={() => set("complete")}
              className={BUTTON}
            >
              Mark as done
            </button>
            <button
              type="button"
              onClick={() => set("not-applicable")}
              className={`${BUTTON} text-muted-foreground`}
            >
              Not applicable
            </button>
          </>
        ) : (
          <button
            type="button"
            onClick={() => set("in-progress")}
            className={BUTTON}
          >
            {m.application_status === "complete"
              ? "Not done yet"
              : "This applies to me"}
          </button>
        )}
      </div>
    </li>
  );
}

// Collapsed by default: finished or dismissed programs stay out of the way.
function CollapsedGroup({
  title,
  matches,
  onSetStatus,
}: {
  title: string;
  matches: Match[];
  onSetStatus: (programId: number, current: Status, next: Status) => void;
}) {
  if (!matches.length) return null;
  return (
    <details className="group rounded-lg border">
      <summary className="flex min-h-11 cursor-pointer list-none items-center justify-between gap-2 px-4 text-sm font-medium [&::-webkit-details-marker]:hidden">
        {title} ({matches.length})
        <ChevronDown
          className="h-4 w-4 transition-transform group-open:rotate-180 motion-reduce:transition-none"
          aria-hidden="true"
        />
      </summary>
      <ul className="grid gap-3 p-3 pt-0 md:grid-cols-2">
        {matches.map((m) => (
          <MatchCard key={m.program.id} m={m} onSetStatus={onSetStatus} />
        ))}
      </ul>
    </details>
  );
}

type MatchesResult = Awaited<ReturnType<typeof fetchProgramMatches>>;

export function ProgramMatches() {
  const { result } = useCached(CACHE_KEYS.programMatches, () =>
    fetchProgramMatches(),
  );
  const state: State = result ? toState(result) : { kind: "loading" };
  const [asking, setAsking] = useState(false);
  const [askError, setAskError] = useState<string | null>(null);
  // Status saves still in flight, so "Ask Equa" waits for them before re-matching.
  const pendingSaves = useRef(new Set<Promise<unknown>>());
  // Decisions made while Equa is thinking: the fresh matches may predate them.
  const changedWhileAsking = useRef<Map<number, Status> | null>(null);

  const setStatus = async (
    programId: number,
    current: Status,
    next: Status,
  ) => {
    if (state.kind !== "ready") return;
    // Update the cache itself, so the new status survives switching tabs.
    const flip = (status: Status) =>
      setCached<MatchesResult>(CACHE_KEYS.programMatches, (prev) =>
        prev && "data" in prev
          ? {
              data: {
                ...prev.data,
                matches: prev.data.matches.map((x) =>
                  x.program.id === programId
                    ? { ...x, application_status: status }
                    : x,
                ),
              },
            }
          : (prev as MatchesResult),
      );
    flip(next); // optimistic
    changedWhileAsking.current?.set(programId, next);
    const save = setApplicationStatus(programId, next);
    pendingSaves.current.add(save);
    const saved = await save.finally(() => pendingSaves.current.delete(save));
    if (!("ok" in saved)) {
      flip(current);
      changedWhileAsking.current?.set(programId, current);
    }
  };

  const askAgain = async () => {
    setAsking(true); // keep showing the current matches while Equa thinks
    setAskError(null);
    changedWhileAsking.current = new Map();
    // Let any "Mark as done" / "Not applicable" land in Postgres first, so the
    // re-match sees it and never brings the program back as in progress.
    await Promise.allSettled([...pendingSaves.current]);
    const fresh = await fetchProgramMatches(true);
    const changed = changedWhileAsking.current;
    changedWhileAsking.current = null;
    if ("data" in fresh) {
      setCached<MatchesResult>(CACHE_KEYS.programMatches, (prev) => {
        const before = prev && "data" in prev ? prev.data.matches : [];
        const freshIds = new Set(fresh.data.matches.map((m) => m.program.id));
        // Programs the user already handled always stay, even if Equa dropped them.
        const kept = before.filter(
          (m) =>
            !freshIds.has(m.program.id) &&
            (changed.get(m.program.id) ?? m.application_status) !==
              "in-progress",
        );
        const matches = [...fresh.data.matches, ...kept].map((m) =>
          changed.has(m.program.id)
            ? { ...m, application_status: changed.get(m.program.id)! }
            : m,
        );
        return { data: { ...fresh.data, matches } };
      });
      invalidate(CACHE_KEYS.aprImpact); // its utility-program card comes from these
    } else if ("notConnected" in fresh) {
      setCached<MatchesResult>(CACHE_KEYS.programMatches, () => fresh);
    } else {
      // Keep the current matches (and the user's progress) on screen.
      setAskError(fresh.message);
    }
    setAsking(false);
  };

  const matches = state.kind === "ready" ? state.data.matches : [];
  const byStatus = (s: Status) =>
    matches.filter((m) => m.application_status === s);
  // Highest confidence first, so the top card is Equa's Best First Step.
  const active = byStatus("in-progress").sort(
    (a, b) => b.confidence - a.confidence,
  );
  const best = active[0];
  const completed = byStatus("complete");
  const notApplicable = byStatus("not-applicable");

  if (state.kind === "not-connected") {
    return (
      <section className="grid gap-2" aria-labelledby="matches-heading">
        <h2
          id="matches-heading"
          className="flex items-center gap-2 text-lg font-semibold"
        >
          <Sparkles className="h-5 w-5" aria-hidden="true" />
          Programs you may qualify for
        </h2>
        <p className="text-sm text-muted-foreground">
          Connect your bank in Settings and Equa will look at your spending to
          find programs you may qualify for.
        </p>
      </section>
    );
  }

  return (
    <section
      className="grid gap-4"
      aria-labelledby="matches-heading"
      aria-busy={state.kind === "loading" || asking}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2
          id="matches-heading"
          className="flex items-center gap-2 text-lg font-semibold"
        >
          <Sparkles className="h-5 w-5" aria-hidden="true" />
          Programs you may qualify for
        </h2>
        {state.kind === "ready" ? (
          <button
            type="button"
            onClick={askAgain}
            disabled={asking}
            className="min-h-11 rounded-md border px-3 text-sm font-medium hover:bg-accent disabled:opacity-50"
          >
            {asking ? "Equa is thinking…" : "Ask Equa"}
          </button>
        ) : null}
      </div>

      {askError ? (
        <p role="status" className="text-sm text-muted-foreground">
          {askError}
        </p>
      ) : null}
      {state.kind === "loading" ? (
        <div className="grid animate-pulse gap-3">
          <span className="h-5 w-3/4 rounded bg-muted" />
          <span className="h-24 rounded-lg bg-muted" />
          <span className="h-24 rounded-lg bg-muted" />
        </div>
      ) : state.kind === "error" ? (
        <p className="text-sm text-muted-foreground">{state.message}</p>
      ) : (
        <>
          {best ? (
            state.data.summary ? (
              <p className="rounded-2xl rounded-tl-sm bg-card px-4 py-3 text-sm shadow-sm ring-1 ring-border">
                <span className="font-semibold">Equa: </span>
                {state.data.summary}
              </p>
            ) : null
          ) : matches.length ? (
            // Nothing left to apply to, so a "go apply" summary would be stale.
            <p className="rounded-2xl rounded-tl-sm bg-card px-4 py-3 text-sm shadow-sm ring-1 ring-border">
              <span className="font-semibold">Equa: </span>
              {completed.length
                ? `You've applied to ${completed.length} program${completed.length === 1 ? "" : "s"}. That's real progress! `
                : "You've gone through every program I found. "}
              Tap &ldquo;Ask Equa&rdquo; and I&apos;ll look for more.
            </p>
          ) : null}
          {state.data.matches.length ? (
            <>
              {active.length ? (
                <ul className="grid gap-3 md:grid-cols-2">
                  {active.map((m) => (
                    <MatchCard
                      key={m.program.id}
                      m={m}
                      onSetStatus={setStatus}
                      best={m === best}
                    />
                  ))}
                </ul>
              ) : null}
              <CollapsedGroup
                title="Completed"
                matches={completed}
                onSetStatus={setStatus}
              />
              <CollapsedGroup
                title="Not applicable"
                matches={notApplicable}
                onSetStatus={setStatus}
              />
            </>
          ) : (
            <p className="text-sm text-muted-foreground">
              Equa didn&apos;t find a strong match yet. As more local programs
              are added, check back.
            </p>
          )}
          <p className="text-xs text-muted-foreground">
            Each agency decides who qualifies. Equa uses your recent
            transactions to point you in the right direction.
          </p>
        </>
      )}
    </section>
  );
}
