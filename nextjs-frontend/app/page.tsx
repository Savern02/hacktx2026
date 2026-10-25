import { Hero } from "@/components/landing/hero";
import { LandingNav } from "@/components/landing/landing-nav";
import { LandingSections } from "@/components/landing/sections";

export default function Home() {
  return (
    <>
      <LandingNav />
      <main>
        <Hero />
        <LandingSections />
      </main>
    </>
  );
}
