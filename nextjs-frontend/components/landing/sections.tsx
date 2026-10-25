"use client";

import { useRef } from "react";
import Link from "next/link";
import gsap from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import { useGSAP } from "@gsap/react";
import {
  FileText,
  Landmark,
  ListChecks,
  MessageCircle,
  ShieldCheck,
  Sparkles,
  UserRound,
  Wallet,
  Brain,
  Scale,
  Building2,
  type LucideIcon,
} from "lucide-react";

gsap.registerPlugin(useGSAP, ScrollTrigger);

const FEATURES: { icon: LucideIcon; title: string; text: string }[] = [
  {
    icon: Wallet,
    title: "Know what's safe to spend",
    text: "Equa takes your balance, subtracts the bills that are coming up, and shows you one number: what's really yours to use.",
  },
  {
    icon: FileText,
    title: "Find programs that can help",
    text: "SNAP, LIHEAP, Medicaid, Lifeline, WIC and more. Equa helps you find what you may qualify for and keeps track of every application.",
  },
  {
    icon: MessageCircle,
    title: "Talk it through",
    text: "Have a problem? Just ask. Equa answers in plain words and can draft the paperwork, like a request to pause a car payment.",
  },
];

const STEPS: { icon: LucideIcon; title: string; text: string }[] = [
  {
    icon: UserRound,
    title: "Tell Equa about you",
    text: "Your name and zip code are enough to start, so Equa can look for help near you.",
  },
  {
    icon: Landmark,
    title: "Connect your bank",
    text: "One tap links a your bank account, that way Equa can see your balance and upcoming bills.",
  },
  {
    icon: Sparkles,
    title: "Get instant advice",
    text: "No spreadsheets, no complicated analytics and no guessing. Equa tells you the one thing worth doing next.",
  },
];
const RESEARCH: { icon: LucideIcon; title: string; text: string }[] = [
  {
    icon: Brain,
    title: "The Cognitive Tax",
    text: "Scarcity restricts cognitive bandwidth. Studies (Wang et al., 2022) show complex budgeting apps actually cause harm. Equa drops this friction to zero.",
  },
  {
    icon: Scale,
    title: "Systemic Inequality",
    text: "The financial system extracts wealth through predatory lending and micro-fees (French & McKillop, 2016). Equa acts as an active shield against these traps.",
  },
  {
    icon: Building2,
    title: "Institutional Scaffolding",
    text: "Education isn't enough. Research (Gale & Levine, 2010; Katnic et al., 2024) proves that bridging the gap requires proactive systems to help users, rather than just financial tips or complicated guidelines.",
  },
];
const PROMISES: { icon: LucideIcon; title: string; text: string }[] = [
  {
    icon: ListChecks,
    title: "One clear next step",
    text: "No walls of charts about money you don't have. Just what matters today.",
  },
  {
    icon: MessageCircle,
    title: "Plain words, always",
    text: "No jargon. If Equa has to use a money term, it explains it.",
  },
  {
    icon: ShieldCheck,
    title: "Your private info stays private",
    text: "Equa will never ask for your passwords, full card numbers or Social Security number.",
  },
];

function SectionHeading({
  id,
  eyebrow,
  title,
  text,
}: {
  id: string;
  eyebrow: string;
  title: string;
  text?: string;
}) {
  return (
    <div data-reveal className="mx-auto max-w-2xl text-center">
      <p className="text-sm font-medium uppercase tracking-wide text-gray-500 dark:text-gray-400">
        {eyebrow}
      </p>
      <h2
        id={id}
        className="mt-2 text-3xl font-bold text-gray-900 sm:text-4xl dark:text-white"
      >
        {title}
      </h2>
      {text ? (
        <p className="mt-3 text-base text-gray-600 dark:text-gray-300">
          {text}
        </p>
      ) : null}
    </div>
  );
}

function IconBadge({ icon: Icon }: { icon: LucideIcon }) {
  return (
    <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-gray-900 text-white dark:bg-white dark:text-gray-900">
      <Icon className="h-5 w-5" aria-hidden="true" />
    </span>
  );
}

export function LandingSections() {
  const root = useRef<HTMLDivElement>(null);

  useGSAP(
    () => {
      const mm = gsap.matchMedia();
      mm.add("(prefers-reduced-motion: no-preference)", () => {
        gsap.utils.toArray<HTMLElement>("[data-reveal]").forEach((el) => {
          gsap.from(el, {
            y: 32,
            autoAlpha: 0,
            duration: 0.8,
            ease: "power3.out",
            scrollTrigger: { trigger: el, start: "top 85%", once: true },
          });
        });
      });
    },
    { scope: root },
  );

  return (
    <div ref={root} className="bg-white dark:bg-gray-950">
      {/* What Equa does */}
      <section
        aria-labelledby="features-heading"
        className="px-4 py-20 sm:py-24"
      >
        <SectionHeading
          id="features-heading"
          eyebrow="Take control"
          title="Finnances take time"
          text="but Equa doesn't"
        />
        <ul className="mx-auto mt-12 grid max-w-5xl gap-4 md:grid-cols-3">
          {FEATURES.map((f) => (
            <li
              key={f.title}
              data-reveal
              className="rounded-2xl border border-gray-200 bg-gray-50 p-6 dark:border-gray-800 dark:bg-gray-900"
            >
              <IconBadge icon={f.icon} />
              <h3 className="mt-4 text-lg font-semibold text-gray-900 dark:text-white">
                {f.title}
              </h3>
              <p className="mt-2 text-sm leading-relaxed text-gray-600 dark:text-gray-300">
                {f.text}
              </p>
            </li>
          ))}
        </ul>
      </section>

      {/* How it works */}
      <section
        aria-labelledby="steps-heading"
        className="bg-gray-50 px-4 py-20 sm:py-24 dark:bg-gray-900"
      >
        <SectionHeading
          id="steps-heading"
          eyebrow="How it works"
          title="Three steps. About two minutes."
        />
        <ol className="mx-auto mt-12 grid max-w-3xl gap-6">
          {STEPS.map((step, i) => (
            <li key={step.title} data-reveal className="flex gap-4">
              <IconBadge icon={step.icon} />
              <div className="min-w-0">
                <p className="text-sm font-medium text-gray-500 dark:text-gray-400">
                  Step {i + 1}
                </p>
                <h3 className="text-lg font-semibold text-gray-900 dark:text-white">
                  {step.title}
                </h3>
                <p className="mt-1 text-sm leading-relaxed text-gray-600 dark:text-gray-300">
                  {step.text}
                </p>
              </div>
            </li>
          ))}
        </ol>
      </section>

      {/* Promises */}
      <section
        aria-labelledby="promises-heading"
        className="px-4 py-20 sm:py-24"
      >
        <SectionHeading
          id="promises-heading"
          eyebrow="Built for real life"
          title="Calm by design"
          text="Equa is made for people who are stretched thin, so it keeps things simple."
        />
        <ul className="mx-auto mt-12 grid max-w-5xl gap-8 md:grid-cols-3">
          {PROMISES.map((p) => (
            <li key={p.title} data-reveal className="text-center">
              <span className="mx-auto flex w-fit">
                <IconBadge icon={p.icon} />
              </span>
              <h3 className="mt-4 text-lg font-semibold text-gray-900 dark:text-white">
                {p.title}
              </h3>
              <p className="mt-2 text-sm leading-relaxed text-gray-600 dark:text-gray-300">
                {p.text}
              </p>
            </li>
          ))}
        </ul>
      </section>

      {/* Backed by Research */}
      <section
        aria-labelledby="research-heading"
        className="bg-gray-50 px-4 py-20 sm:py-24 dark:bg-gray-900"

      >
        <SectionHeading
          id="research-heading"
          eyebrow="The Why"
          title="Backed by Research"
          text="Traditional financial tools ignore the structural realities of systemic financial barriers. Equa is built on what works according to economic research."
        />
        <ul className="mx-auto mt-12 grid max-w-5xl gap-4 md:grid-cols-3">
          {RESEARCH.map((r) => (
            <li
              key={r.title}
              data-reveal
              className="rounded-2xl border border-gray-200 bg-gray-50 p-6 dark:border-gray-800 dark:bg-gray-900"
            >
              <IconBadge icon={r.icon} />
              <h3 className="mt-4 text-lg font-semibold text-gray-900 dark:text-white">
                {r.title}
              </h3>
              <p className="mt-2 text-sm leading-relaxed text-gray-600 dark:text-gray-300">
                {r.text}
              </p>
            </li>
          ))}
        </ul>
      </section>

      {/* Final call to action */}
      <section className="bg-gray-900 px-4 py-20 text-center sm:py-24 dark:bg-gray-800">
        <div data-reveal className="mx-auto max-w-xl">
          <h2 className="text-3xl font-bold text-white sm:text-4xl">
            Need financal help? Use Equa.
          </h2>
          <p className="mt-3 text-base text-gray-300">
            Tell Equa what&apos;s going on. You don&apos;t have to figure it out
            alone.
          </p>
          <Link
            href="/register"
            className="mt-8 inline-flex min-h-12 w-full items-center justify-center rounded-md bg-white px-8 text-base font-semibold text-gray-900 transition-colors hover:bg-gray-200 sm:w-auto"
          >
            Talk to Equa
          </Link>
        </div>
      </section>

      <footer className="px-4 py-8 text-center text-sm text-gray-500 dark:text-gray-400">
        Equa · <a href="https://www.linkedin.com/in/jonah-sanders-/">Jonah Sanders</a> · <a href="https://hacktx26.devpost.com">Built at HackTX 2026</a>
      </footer>
    </div>
  );
}
