"use client";

import { useEffect, useState } from "react";
import { ExternalLink, MapPin, Phone } from "lucide-react";

import type { ProgramRead, ProgramsForUser } from "@/app/clientService";
import {
  changeCity,
  fetchMyPrograms,
} from "@/components/actions/programs-action";

function ProgramCard({ program }: { program: ProgramRead }) {
  const link = program.apply_url || program.info_url;
  return (
    <li className="grid gap-2 rounded-lg border bg-card p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <h4 className="min-w-0 break-words font-medium">{program.name}</h4>
        <span className="shrink-0 rounded-full bg-muted px-2 py-0.5 text-xs text-muted-foreground">
          {program.jurisdiction}
        </span>
      </div>
      {program.summary ? (
        <p className="line-clamp-3 text-sm text-muted-foreground">
          {program.summary}
        </p>
      ) : null}
      <div className="flex flex-wrap gap-2">
        {link ? (
          <a
            href={link}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex min-h-11 items-center gap-1.5 rounded-md border px-3 text-sm font-medium hover:bg-accent"
          >
            {program.apply_url ? "How to apply" : "Learn more"}
            <ExternalLink className="h-4 w-4" aria-hidden="true" />
            <span className="sr-only">(opens in a new tab)</span>
          </a>
        ) : null}
        {program.phone ? (
          <a
            href={`tel:${program.phone}`}
            className="inline-flex min-h-11 items-center gap-1.5 rounded-md border px-3 text-sm font-medium hover:bg-accent"
          >
            <Phone className="h-4 w-4" aria-hidden="true" />
            {program.phone}
          </a>
        ) : null}
      </div>
    </li>
  );
}

export function ProgramsNearYou() {
  const [data, setData] = useState<ProgramsForUser | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [federal, setFederal] = useState<ProgramRead[]>([]);
  const [loadingMore, setLoadingMore] = useState(false);
  const [picking, setPicking] = useState(false);
  const [version, setVersion] = useState(0);

  useEffect(() => {
    let cancelled = false;
    fetchMyPrograms().then((result) => {
      if (cancelled) return;
      if ("data" in result) {
        setData(result.data);
        setFederal(result.data.federal);
        setError(null);
      } else {
        setError(result.message);
      }
    });
    return () => {
      cancelled = true;
    };
  }, [version]);

  const showMore = async () => {
    setLoadingMore(true);
    const result = await fetchMyPrograms(federal.length);
    setLoadingMore(false);
    if ("data" in result) setFederal((f) => [...f, ...result.data.federal]);
  };

  const pickCity = async (id: number) => {
    const result = await changeCity(id);
    if ("data" in result) {
      setPicking(false);
      setVersion((v) => v + 1);
    } else {
      setError(result.message);
    }
  };

  if (error && !data) {
    return <p className="text-sm text-muted-foreground">{error}</p>;
  }
  if (!data) {
    return (
      <div className="grid animate-pulse gap-3" aria-busy="true">
        <span className="h-6 w-48 rounded bg-muted" />
        <span className="h-24 rounded-lg bg-muted" />
        <span className="h-24 rounded-lg bg-muted" />
      </div>
    );
  }

  const location = data.location;
  const place = location?.display_name;

  return (
    <section className="grid gap-4" aria-labelledby="near-you-heading">
      <div className="grid gap-1">
        <h2 id="near-you-heading" className="text-lg font-semibold">
          {place ? `Programs near ${place}` : "Programs for you"}
        </h2>
        {location && place ? (
          <p className="flex flex-wrap items-center gap-x-2 text-sm text-muted-foreground">
            <MapPin className="h-4 w-4" aria-hidden="true" />
            Based on ZIP {location.zip}.
            {location.alternates.length ? (
              <button
                type="button"
                onClick={() => setPicking((p) => !p)}
                className="min-h-11 font-medium text-foreground underline underline-offset-2"
                aria-expanded={picking}
              >
                Not right? Change city.
              </button>
            ) : null}
          </p>
        ) : (
          <p className="text-sm text-muted-foreground">
            Add your ZIP code in Settings so Equa can find programs near you.
          </p>
        )}
        {picking && location ? (
          <ul className="flex flex-wrap gap-2" aria-label="Choose your city">
            {location.alternates.map((alt) => (
              <li key={alt.id}>
                <button
                  type="button"
                  onClick={() => pickCity(alt.id)}
                  className="min-h-11 rounded-md border px-3 text-sm hover:bg-accent"
                >
                  {alt.name}
                </button>
              </li>
            ))}
          </ul>
        ) : null}
      </div>

      {data.gathering.length ? (
        <p
          role="status"
          className="rounded-lg border border-dashed px-4 py-3 text-sm"
        >
          Equa is still gathering programs for {data.gathering.join(" and ")}.
          Check back soon. Federal programs are ready below.
        </p>
      ) : null}

      {data.local.length ? (
        <ul className="grid gap-3 md:grid-cols-2">
          {data.local.map((p) => (
            <ProgramCard key={p.id} program={p} />
          ))}
        </ul>
      ) : !data.gathering.length && place ? (
        <p className="text-sm text-muted-foreground">
          Equa hasn&apos;t found local programs for {place} yet.
        </p>
      ) : null}

      <h3 className="mt-2 font-semibold">Federal programs</h3>
      {federal.length ? (
        <>
          <ul className="grid gap-3 md:grid-cols-2">
            {federal.map((p) => (
              <ProgramCard key={p.id} program={p} />
            ))}
          </ul>
          {federal.length < data.federal_total ? (
            <button
              type="button"
              onClick={showMore}
              disabled={loadingMore}
              className="min-h-11 rounded-md border px-4 text-sm font-medium hover:bg-accent sm:w-fit"
            >
              {loadingMore ? "Loading…" : "Show more"}
            </button>
          ) : null}
        </>
      ) : (
        <p className="text-sm text-muted-foreground">
          Federal programs will show here once they&apos;ve been loaded.
        </p>
      )}
    </section>
  );
}
