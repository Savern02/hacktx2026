"use server";

import { cookies } from "next/headers";
import { getBalance, type BalanceRead } from "@/app/clientService";

export async function fetchBalance(): Promise<
  { data: BalanceRead } | { message: string }
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

  if (error || !data) {
    return { message: "Couldn't load your balance. Please try again." };
  }

  return { data };
}
