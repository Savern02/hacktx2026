"use client";

import { useRef } from "react";
import Link from "next/link";
import gsap from "gsap";
import { useGSAP } from "@gsap/react";

import { cn } from "@/lib/utils";

gsap.registerPlugin(useGSAP);

// Sample conversation showing how Equa helps, in order.
const DEMO_CHAT = [
  {
    from: "equa",
    text: "Hi, I'm Equa! Tell me what's going on with your money and I'll help you figure out the next step, from what's safe to spend to programs that can help.",
  },
  { from: "user", text: "My car payment is due Friday and I'm short." },
  {
    from: "equa",
    text: "I've got you. After your bills, you have $764.50 safe to spend.",
  },
  {
    from: "equa",
    text: "You may qualify for an auto-loan deferment. Want me to draft the request?",
  },
  { from: "user", text: "Yes please!" },
] as const;

export function Hero() {
  const root = useRef<HTMLElement>(null);

  useGSAP(
    () => {
      // Content starts hidden (see `invisible` below) to avoid a flash before animating.
      gsap.set(root.current, { autoAlpha: 1 });

      const mm = gsap.matchMedia();

      mm.add("(prefers-reduced-motion: no-preference)", () => {
        const tl = gsap.timeline({ defaults: { ease: "power3.out" } });

        tl.from("[data-hero-intro]", {
          y: 32,
          autoAlpha: 0,
          duration: 0.8,
          stagger: 0.2,
        })
          .from(
            "[data-hero-card]",
            { y: 40, autoAlpha: 0, duration: 1 },
            "-=0.6",
          )
          .from(
            "[data-hero-bubble]",
            {
              y: 12,
              scale: 0.9,
              autoAlpha: 0,
              duration: 0.45,
              ease: "back.out(1.7)",
              stagger: 0.6,
            },
            "-=0.3",
          )
          .from("[data-hero-cta]", { y: 24, autoAlpha: 0, duration: 0.6 });

        // Gentle, endless float on a wrapper so it doesn't fight the entrance tween.
        gsap.to("[data-hero-float]", {
          y: -10,
          duration: 3,
          ease: "sine.inOut",
          yoyo: true,
          repeat: -1,
        });
      });
    },
    { scope: root },
  );

  return (
    <section
      ref={root}
      className="invisible flex min-h-screen flex-col items-center justify-center bg-gray-50 px-4 py-12 dark:bg-gray-900"
    >
      {/* Without JS, GSAP never reveals the section, so show it right away. */}
      <noscript>
        <style>{`section.invisible{visibility:visible}`}</style>
      </noscript>

      <div className="flex w-full max-w-md flex-col items-center text-center">
        <p
          data-hero-intro
          className="text-sm font-medium uppercase tracking-wide text-gray-500 dark:text-gray-400"
        >
          Equality Finances
        </p>
        <h1
          data-hero-intro
          className="mt-2 text-6xl font-bold text-gray-900 sm:text-8xl dark:text-white"
        >
          Equa
        </h1>
        <p
          data-hero-intro
          className="mt-4 text-2xl font-semibold text-gray-700 sm:text-3xl dark:text-gray-200"
        >
          Have a problem? Use Equa.
        </p>

        <div data-hero-float className="mt-8 w-full">
          <div
            data-hero-card
            className="rounded-2xl border border-gray-200 bg-white p-4 text-left shadow-sm dark:border-gray-700 dark:bg-gray-800"
          >
            <div className="mb-4 flex items-center gap-3 border-b border-gray-200 pb-3 dark:border-gray-700">
              <span
                aria-hidden="true"
                className="flex h-9 w-9 items-center justify-center rounded-full bg-gray-900 text-sm font-bold text-white dark:bg-white dark:text-gray-900"
              >
                E
              </span>
              <div>
                <p className="text-sm font-semibold text-gray-900 dark:text-white">
                  Equa
                </p>
                <p className="text-xs text-gray-500 dark:text-gray-400">
                  Here to help
                </p>
              </div>
            </div>
            <ol
              aria-label="Example conversation with Equa"
              className="flex flex-col gap-2 text-sm leading-relaxed"
            >
              {DEMO_CHAT.map((message, i) => (
                <li
                  key={i}
                  data-hero-bubble
                  className={cn(
                    "max-w-[85%] rounded-2xl px-3 py-2",
                    message.from === "user"
                      ? "self-end rounded-br-sm bg-gray-900 text-white dark:bg-white dark:text-gray-900"
                      : "self-start rounded-bl-sm bg-gray-100 text-gray-800 dark:bg-gray-700 dark:text-gray-100",
                  )}
                >
                  <span className="sr-only">
                    {message.from === "user" ? "You: " : "Equa: "}
                  </span>
                  {message.text}
                </li>
              ))}
            </ol>
          </div>
        </div>

        <div
          id="hero-cta"
          data-hero-cta
          className="mt-8 flex w-full flex-col gap-3 sm:w-auto sm:flex-row"
        >
          <Link
            href="/register"
            className="inline-flex min-h-12 items-center justify-center rounded-md bg-gray-900 px-8 text-base font-semibold text-white transition-colors hover:bg-gray-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-gray-900 focus-visible:ring-offset-2 dark:bg-white dark:text-gray-900 dark:hover:bg-gray-200 dark:focus-visible:ring-white dark:focus-visible:ring-offset-gray-900"
          >
            Talk to Equa
          </Link>
          <Link
            href="/login"
            className="inline-flex min-h-12 items-center justify-center rounded-md border border-gray-300 bg-white px-8 text-base font-semibold text-gray-900 transition-colors hover:bg-gray-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-gray-900 focus-visible:ring-offset-2 dark:border-gray-600 dark:bg-transparent dark:text-white dark:hover:bg-gray-800 dark:focus-visible:ring-white dark:focus-visible:ring-offset-gray-900"
          >
            I already have an account
          </Link>
        </div>
      </div>
    </section>
  );
}
