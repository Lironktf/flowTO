import { MotionConfig } from "framer-motion";
import { useLenis } from "./scroll/useLenis";
import { Nav } from "./sections/Nav";
import { Hero } from "./sections/Hero";
import { Numbers } from "./sections/Numbers";
import { Scenario } from "./sections/Scenario";
import { TwoModes } from "./sections/TwoModes";
import { Engine } from "./sections/Engine";
import { HowItWorks } from "./sections/HowItWorks";
import { CTA } from "./sections/CTA";
import { Footer } from "./sections/Footer";

export function LandingApp() {
  useLenis();
  return (
    <MotionConfig reducedMotion="user">
      <Nav />
      <main>
        {/* Hero + Numbers share a positioning context so the CN Tower can
            emerge from behind the stats band (see hero.css). */}
        <div className="hero-stack">
          <Hero />
          <Numbers />
        </div>
        <Scenario />
        <TwoModes />
        <Engine />
        <HowItWorks />
        <CTA />
      </main>
      <Footer />
    </MotionConfig>
  );
}
