"use client";

import { useEffect, useRef, useState } from "react";
import { SendHorizontal } from "lucide-react";

import { sendChat } from "@/components/actions/chat-action";
import { cn } from "@/lib/utils";

// `failed` marks Equa's error notices, which aren't sent back to the AI.
type Message = {
  id: number;
  from: "user" | "equa";
  text: string;
  failed?: boolean;
};

// The backend accepts at most 40 messages of history.
const MAX_HISTORY = 40;

const GREETING =
  "Hi, I'm Equa! Have a problem? Tell me what's going on and we'll figure out the next step together.";

export function EquaChat() {
  const [messages, setMessages] = useState<Message[]>([
    { id: 0, from: "equa", text: GREETING },
  ]);
  const [draft, setDraft] = useState("");
  const [typing, setTyping] = useState(false);
  const endRef = useRef<HTMLLIElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, typing]);

  const send = async (e: React.FormEvent) => {
    e.preventDefault();
    const text = draft.trim();
    if (!text || typing) return;

    const next: Message[] = [
      ...messages,
      { id: messages.length, from: "user", text },
    ];
    setMessages(next);
    setDraft("");
    setTyping(true);

    const history = next
      .filter((m) => !m.failed)
      .slice(-MAX_HISTORY)
      .map((m) => ({ role: m.from, text: m.text }));
    const result = await sendChat(history);

    setMessages((m) => [
      ...m,
      "reply" in result
        ? { id: m.length, from: "equa", text: result.reply }
        : { id: m.length, from: "equa", text: result.message, failed: true },
    ]);
    setTyping(false);
    inputRef.current?.focus();
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <ol
        aria-label="Conversation with Equa"
        aria-live="polite"
        className="flex flex-1 flex-col gap-2 overflow-y-auto p-3 text-sm"
      >
        {messages.map((m) => (
          <li
            key={m.id}
            className={cn(
              "max-w-[85%] whitespace-pre-wrap break-words rounded-2xl px-3 py-2",
              m.from === "user"
                ? "self-end rounded-br-sm bg-primary text-primary-foreground"
                : "self-start rounded-bl-sm bg-muted text-foreground",
            )}
          >
            <span className="sr-only">
              {m.from === "user" ? "You: " : "Equa: "}
            </span>
            {m.text}
          </li>
        ))}
        {typing ? (
          <li className="self-start rounded-2xl rounded-bl-sm bg-muted px-3 py-2 text-muted-foreground">
            <span className="animate-pulse motion-reduce:animate-none">
              Equa is typing…
            </span>
          </li>
        ) : null}
        <li ref={endRef} aria-hidden="true" />
      </ol>

      <form onSubmit={send} className="flex items-center gap-2 border-t p-2">
        <label htmlFor="equa-chat-input" className="sr-only">
          Message Equa
        </label>
        <input
          ref={inputRef}
          id="equa-chat-input"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="Ask Equa anything…"
          autoComplete="off"
          // 16px text stops iOS Safari from zooming in on focus.
          className="min-h-11 min-w-0 flex-1 rounded-full border bg-background px-4 text-base focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring sm:text-sm"
        />
        <button
          type="submit"
          aria-label="Send message"
          disabled={!draft.trim() || typing}
          className="inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-primary text-primary-foreground transition-opacity disabled:opacity-50"
        >
          <SendHorizontal className="h-5 w-5" aria-hidden="true" />
        </button>
      </form>
    </div>
  );
}
