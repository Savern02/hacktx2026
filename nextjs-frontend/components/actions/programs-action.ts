"use server";

import { cookies } from "next/headers";
import {
  changeMyLocation,
  getMyPrograms,
  type LocationRead,
  type ProgramsForUser,
} from "@/app/clientService";

async function authHeaders() {
  const token = (await cookies()).get("accessToken")?.value;
  return token ? { Authorization: `Bearer ${token}` } : null;
}

export async function fetchMyPrograms(
  federalOffset = 0,
): Promise<{ data: ProgramsForUser } | { message: string }> {
  const headers = await authHeaders();
  if (!headers) return { message: "Please log in again." };
  const { data, error } = await getMyPrograms({
    headers,
    query: { federal_limit: 10, federal_offset: federalOffset },
  });
  if (error || !data) {
    return {
      message: "Equa couldn't load programs just now. Let's try again.",
    };
  }
  return { data };
}

export async function changeCity(
  jurisdictionId: number,
): Promise<{ data: LocationRead } | { message: string }> {
  const headers = await authHeaders();
  if (!headers) return { message: "Please log in again." };
  const { data, error } = await changeMyLocation({
    headers,
    body: { jurisdiction_id: jurisdictionId },
  });
  if (error || !data) {
    return { message: "Equa couldn't change your city. Let's try again." };
  }
  return { data };
}
