"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

import { cn } from "@/lib/utils";

/**
 * Top bar with the hero's two buttons. It only shows once the user has scrolled
 * past the hero buttons (they've left the top of the viewport), so it never
 * duplicates buttons that are still on screen.
 */
export function LandingNav({ targetId = "hero-cta" }: { targetId?: string }) {
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    const target = document.getElementById(targetId);
    if (!target) return;

    const observer = new IntersectionObserver(([entry]) => {
      // Hidden *above* the viewport = scrolled past. Below the fold doesn't count.
      setVisible(!entry.isIntersecting && entry.boundingClientRect.top < 0);
    });
    observer.observe(target);
    return () => observer.disconnect();
  }, [targetId]);

  return (
    <header
      aria-hidden={!visible}
      inert={!visible}
      className={cn(
        "fixed inset-x-0 top-0 z-50 border-b border-gray-200 bg-white/90 backdrop-blur transition-transform duration-300 motion-reduce:transition-none dark:border-gray-800 dark:bg-gray-900/90",
        visible ? "translate-y-0" : "-translate-y-full",
      )}
    >
      <nav className="mx-auto flex max-w-5xl items-center justify-between gap-3 px-4 py-2">
        <Link
          href="/"
          className="flex min-h-11 items-center text-xl font-bold text-gray-900 dark:text-white"
        >
          Equa
        </Link>
        <div className="flex items-center gap-2">
          <Link
            href="/login"
            className="inline-flex min-h-11 items-center justify-center rounded-md border border-gray-300 bg-white px-3 text-sm font-semibold text-gray-900 transition-colors hover:bg-gray-100 sm:px-4 dark:border-gray-600 dark:bg-transparent dark:text-white dark:hover:bg-gray-800"
          >
            {/* Full label won't fit next to the other button on a phone. */}
            <span className="sm:hidden">Log in</span>
            <span className="hidden sm:inline">I already have an account</span>
          </Link>
          <Link
            href="/register"
            className="inline-flex min-h-11 items-center justify-center rounded-md bg-gray-900 px-3 text-sm font-semibold text-white transition-colors hover:bg-gray-700 sm:px-4 dark:bg-white dark:text-gray-900 dark:hover:bg-gray-200"
          >
            Talk to Equa
          </Link>
        </div>
      </nav>
    </header>
  );
}
