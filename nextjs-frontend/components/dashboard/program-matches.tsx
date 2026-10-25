"use client";

import { useEffect, useState } from "react";
import { ExternalLink, Sparkles } from "lucide-react";

import type { ProgramMatches as Matches } from "@/app/clientService";
import {
  fetchProgramMatches,
  setApplicationStatus,
} from "@/components/actions/finance-action";
import { StatusProgressBar } from "@/components/dashboard/status-progress-bar";

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

export function ProgramMatches() {
  const [state, setState] = useState<State>({ kind: "loading" });
  const [asking, setAsking] = useState(false);

  useEffect(() => {
    let cancelled = false;
    fetchProgramMatches().then((result) => {
      if (!cancelled) setState(toState(result));
    });
    return () => {
      cancelled = true;
    };
  }, []);

  const toggle = async (
    programId: number,
    current: "in-progress" | "complete",
  ) => {
    const next = current === "complete" ? "in-progress" : "complete";
    if (state.kind !== "ready") return;
    const flip = (status: typeof next) =>
      setState((prev) =>
        prev.kind === "ready"
          ? {
              ...prev,
              data: {
                ...prev.data,
                matches: prev.data.matches.map((x) =>
                  x.program.id === programId
                    ? { ...x, application_status: status }
                    : x,
                ),
              },
            }
          : prev,
      );
    flip(next); // optimistic
    const result = await setApplicationStatus(programId, next);
    if (!("ok" in result)) flip(current);
  };

  const askAgain = async () => {
    setAsking(true);
    setState(toState(await fetchProgramMatches(true)));
    setAsking(false);
  };

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
            {asking ? "Equa is thinking…" : "Ask Equa again"}
          </button>
        ) : null}
      </div>

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
          {state.data.summary ? (
            <p className="rounded-2xl rounded-tl-sm bg-card px-4 py-3 text-sm shadow-sm ring-1 ring-border">
              <span className="font-semibold">Equa: </span>
              {state.data.summary}
            </p>
          ) : null}
          {state.data.matches.length ? (
            <ul className="grid gap-3 md:grid-cols-2">
              {state.data.matches.map((m) => (
                <li
                  key={m.program.id}
                  className="grid gap-3 rounded-lg border bg-card p-4"
                >
                  <StatusProgressBar
                    status={m.application_status}
                    label={m.program.name}
                  />
                  <p className="text-xs text-muted-foreground">
                    {m.program.jurisdiction}
                  </p>
                  <p className="text-sm">{m.reason}</p>
                  <div className="flex flex-wrap gap-2">
                    {m.application_url ? (
                      <a
                        href={m.application_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="inline-flex min-h-11 items-center gap-1.5 rounded-md bg-primary px-3 text-sm font-medium text-primary-foreground hover:bg-primary/90"
                      >
                        Apply
                        <ExternalLink className="h-4 w-4" aria-hidden="true" />
                        <span className="sr-only">(opens in a new tab)</span>
                      </a>
                    ) : null}
                    <button
                      type="button"
                      onClick={() => toggle(m.program.id, m.application_status)}
                      className="min-h-11 rounded-md border px-3 text-sm font-medium hover:bg-accent"
                    >
                      {m.application_status === "complete"
                        ? "Not done yet"
                        : "Mark as done"}
                    </button>
                  </div>
                </li>
              ))}
            </ul>
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
