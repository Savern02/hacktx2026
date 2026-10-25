"use server";

import { cookies } from "next/headers";
import { sendMessage, type ChatMessage } from "@/app/clientService";

export async function sendChat(
  messages: ChatMessage[],
): Promise<{ reply: string } | { message: string }> {
  const cookieStore = await cookies();
  const token = cookieStore.get("accessToken")?.value;

  if (!token) {
    return { message: "Please log in again so Equa can help you." };
  }

  const { data, error } = await sendMessage({
    body: { messages },
    headers: {
      Authorization: `Bearer ${token}`,
    },
  });

  if (error || !data) {
    return {
      message:
        "Sorry, Equa had trouble thinking just now. Could you try sending that again?",
    };
  }

  return { reply: data.reply };
}
