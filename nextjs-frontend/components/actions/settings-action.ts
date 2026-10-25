"use server";

import { cookies } from "next/headers";
import {
  connectBank,
  usersCurrentUser,
  usersPatchCurrentUser,
  type UserRead,
} from "@/app/clientService";
import { profileSchema } from "@/lib/definitions";

async function authHeaders() {
  const token = (await cookies()).get("accessToken")?.value;
  return token ? { Authorization: `Bearer ${token}` } : null;
}

export async function fetchProfile(): Promise<
  { data: UserRead } | { message: string }
> {
  const headers = await authHeaders();
  if (!headers) return { message: "Please log in again." };

  const { data, error } = await usersCurrentUser({ headers });
  if (error || !data) {
    return { message: "Equa couldn't load your settings. Let's try again." };
  }
  return { data };
}

export async function saveProfile(input: {
  full_name: string;
  zip_code: string;
}): Promise<
  | { data: UserRead }
  | { message: string; fieldErrors?: Record<string, string[]> }
> {
  const headers = await authHeaders();
  if (!headers) return { message: "Please log in again." };

  const parsed = profileSchema.safeParse(input);
  if (!parsed.success) {
    return {
      message: "Let's fix a couple of things first.",
      fieldErrors: parsed.error.flatten().fieldErrors,
    };
  }

  const { data, error } = await usersPatchCurrentUser({
    headers,
    body: parsed.data,
  });
  if (error || !data) {
    return { message: "Equa couldn't save that. Let's try again." };
  }
  return { data };
}

export async function connectBankAccount(): Promise<
  { customerId: string } | { message: string }
> {
  const headers = await authHeaders();
  if (!headers) return { message: "Please log in again." };

  const { data, error } = await connectBank({ headers });
  if ((error as { detail?: unknown })?.detail === "PROFILE_INCOMPLETE") {
    return { message: "Save your name and zip code first, then connect." };
  }
  if (error || !data) {
    return {
      message: "Equa couldn't reach the bank just now. Let's try again.",
    };
  }
  return { customerId: data.nessie_customer_id };
}
