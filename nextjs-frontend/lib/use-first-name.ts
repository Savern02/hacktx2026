"use client";

import { fetchProfile } from "@/components/actions/settings-action";
import { CACHE_KEYS, useCached } from "@/lib/data-cache";

/** First word of a full name, or undefined if it's blank. */
export function firstNameOf(fullName?: string | null): string | undefined {
  return fullName?.trim().split(/\s+/)[0] || undefined;
}

/**
 * The user's first name from their saved profile, or undefined if none is set.
 * Shares the Settings cache entry, so saving a new name updates every greeting.
 */
export function useFirstName(): string | undefined {
  const { result } = useCached(CACHE_KEYS.profile, fetchProfile);
  if (!result || !("data" in result)) return undefined;
  return firstNameOf(result.data.full_name);
}
