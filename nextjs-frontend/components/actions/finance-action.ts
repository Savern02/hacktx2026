"use server";

import { cookies } from "next/headers";
import {
  getMyFinancialHealth,
  getMyProgramMatches,
  type FinancialHealth,
  type ProgramMatches,
} from "@/app/clientService";

type Result<T> = { data: T } | { notConnected: true } | { message: string };

async function authHeaders() {
  const token = (await cookies()).get("accessToken")?.value;
  return token ? { Authorization: `Bearer ${token}` } : null;
}

function notConnected(error: unknown): boolean {
  return (error as { detail?: unknown })?.detail === "BANK_NOT_CONNECTED";
}

export async function fetchFinancialHealth(): Promise<Result<FinancialHealth>> {
  const headers = await authHeaders();
  if (!headers) return { message: "Please log in again." };
  const { data, error } = await getMyFinancialHealth({ headers });
  if (notConnected(error)) return { notConnected: true };
  if (error || !data) {
    return {
      message:
        "Equa couldn't read your transactions just now. Let's try again.",
    };
  }
  return { data };
}

export async function fetchProgramMatches(
  refresh = false,
): Promise<Result<ProgramMatches>> {
  const headers = await authHeaders();
  if (!headers) return { message: "Please log in again." };
  const { data, error } = await getMyProgramMatches({
    headers,
    query: { refresh },
  });
  if (notConnected(error)) return { notConnected: true };
  if (error || !data) {
    return { message: "Equa had trouble thinking just now. Let's try again." };
  }
  return { data };
}
