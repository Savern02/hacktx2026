"use client";

import { useEffect, useState } from "react";
import { ExternalLink, Sparkles } from "lucide-react";

import type { ProgramMatches as Matches } from "@/app/clientService";
import { fetchProgramMatches } from "@/components/actions/finance-action";

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
              {state.data.matches.map(({ program, reason }) => {
                const link = program.apply_url || program.info_url;
                return (
                  <li
                    key={program.id}
                    className="grid gap-2 rounded-lg border bg-card p-4"
                  >
                    <div className="flex flex-wrap items-start justify-between gap-2">
                      <h3 className="min-w-0 break-words font-medium">
                        {program.name}
                      </h3>
                      <span className="shrink-0 rounded-full bg-muted px-2 py-0.5 text-xs text-muted-foreground">
                        {program.jurisdiction}
                      </span>
                    </div>
                    <p className="text-sm">{reason}</p>
                    {link ? (
                      <a
                        href={link}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="inline-flex min-h-11 w-fit items-center gap-1.5 rounded-md border px-3 text-sm font-medium hover:bg-accent"
                      >
                        Learn how to apply
                        <ExternalLink className="h-4 w-4" aria-hidden="true" />
                        <span className="sr-only">(opens in a new tab)</span>
                      </a>
                    ) : null}
                  </li>
                );
              })}
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
