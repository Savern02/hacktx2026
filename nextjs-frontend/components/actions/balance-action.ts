"use server";

import { cookies } from "next/headers";
import { getBalance, type BalanceRead } from "@/app/clientService";

export async function fetchBalance(): Promise<
  { data: BalanceRead } | { notConnected: true } | { message: string }
> {
  const cookieStore = await cookies();
  const token = cookieStore.get("accessToken")?.value;

  if (!token) {
    return { message: "No access token found" };
  }

  const { data, error } = await getBalance({
    headers: {
      Authorization: `Bearer ${token}`,
    },
  });

  if ((error as { detail?: unknown })?.detail === "BANK_NOT_CONNECTED") {
    return { notConnected: true };
  }

  if (error || !data) {
    return {
      message: "Hmm, Equa couldn't reach your bank just now. Let's try again.",
    };
  }

  return { data };
}
