"use client";

import { useCallback, useEffect, useSyncExternalStore } from "react";

/**
 * A tiny in-memory cache for dashboard data.
 *
 * Switching tabs unmounts a tab's content, so without this every visit refetched
 * from the server. Now a result is fetched once and reused until something that
 * changes it calls `invalidate` (connect bank, save settings, log out) or the
 * component asks for a `reload` (e.g. "Ask Equa again").
 *
 * Error results (objects with a `message`) aren't kept, so the next visit retries.
 */

export const CACHE_KEYS = {
  balance: "balance",
  health: "health",
  aprImpact: "apr-impact",
  lenderRequest: "lender-request",
  programMatches: "program-matches",
  profile: "profile",
  planDecisions: "plan-decisions",
  planOwnSteps: "plan-own-steps",
} as const;

type Entry = { value: unknown; keep: boolean };

const entries = new Map<string, Entry>();
const inflight = new Map<string, Promise<unknown>>();
const listeners = new Set<() => void>();

function emit() {
  listeners.forEach((listener) => listener());
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function isError(value: unknown): boolean {
  return typeof value === "object" && value !== null && "message" in value;
}

async function load<T>(key: string, fetcher: () => Promise<T>): Promise<T> {
  const running = inflight.get(key);
  if (running) return running as Promise<T>; // one request per key at a time
  const promise = fetcher()
    .then((value) => {
      entries.set(key, { value, keep: !isError(value) });
      return value;
    })
    .finally(() => {
      inflight.delete(key);
      emit();
    });
  inflight.set(key, promise);
  return promise;
}

/** Drop cached results so mounted users refetch now and others on their next visit. */
export function invalidate(...keys: string[]) {
  keys.forEach((key) => entries.delete(key));
  emit();
}

/** Forget everything (e.g. on log out, so the next user never sees old data). */
export function clearCache() {
  entries.clear();
  emit();
}

/** Read a cached result without fetching (undefined if there isn't one). */
export function peekCached<T>(key: string): T | undefined {
  return entries.get(key)?.value as T | undefined;
}

/** Write a result directly, e.g. after an optimistic update. */
export function setCached<T>(
  key: string,
  update: (current: T | undefined) => T,
) {
  const current = entries.get(key)?.value as T | undefined;
  const value = update(current);
  entries.set(key, { value, keep: !isError(value) });
  emit();
}

export function useCached<T>(key: string, fetcher: () => Promise<T>) {
  const entry = useSyncExternalStore(
    subscribe,
    () => entries.get(key),
    () => undefined,
  );
  const missing = entry === undefined || !entry.keep;

  useEffect(() => {
    // Only fetch when there's no usable cached result (first visit, invalidated, or error).
    if (missing && !inflight.has(key)) void load(key, fetcher);
    // fetcher is deliberately left out of the deps: callers pass inline functions.
  }, [key, missing]);

  const reload = useCallback(
    (override?: () => Promise<T>) => {
      entries.delete(key); // show the loading state, then the fresh result
      emit();
      return load(key, override ?? fetcher);
    },
    [key],
  );

  return {
    /** The latest result (including an error result), or undefined while loading. */
    result: entry?.value as T | undefined,
    loading: entry === undefined,
    reload,
  };
}
