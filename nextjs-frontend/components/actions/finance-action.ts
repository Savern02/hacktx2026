"use server";

import { cookies } from "next/headers";
import {
  getMyFinancialHealth,
  draftMyLenderRequest,
  getMyAprImpact,
  getMyProgramMatches,
  setMyApplicationStatus,
  type AprImpact,
  type FinancialHealth,
  type LenderRequest,
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

export async function setApplicationStatus(
  programId: number,
  status: "in-progress" | "complete" | "not-applicable",
): Promise<{ ok: true } | { message: string }> {
  const headers = await authHeaders();
  if (!headers) return { message: "Please log in again." };
  const { error } = await setMyApplicationStatus({
    headers,
    path: { program_id: programId },
    body: { status },
  });
  if (error) return { message: "Equa couldn't save that. Let's try again." };
  return { ok: true };
}

export async function fetchAprImpact(): Promise<Result<AprImpact>> {
  const headers = await authHeaders();
  if (!headers) return { message: "Please log in again." };
  const { data, error } = await getMyAprImpact({ headers });
  if (notConnected(error)) return { notConnected: true };
  if (error || !data) {
    return {
      message: "Equa couldn't read your loans just now. Let's try again.",
    };
  }
  return { data };
}

export async function draftLenderRequest(
  goal: "rate" | "deferment" = "rate",
): Promise<{ data: LenderRequest } | { message: string }> {
  const headers = await authHeaders();
  if (!headers) return { message: "Please log in again." };
  const { data, error } = await draftMyLenderRequest({
    headers,
    query: { goal },
  });
  if (error || !data) {
    return {
      message: "Equa couldn't write the request just now. Let's try again.",
    };
  }
  return { data };
}
