import { useEffect } from "react";
import Lenis from "lenis";
import { setScroll, setPointer } from "./scrollStore";
import { prefersReducedMotion } from "../scene/useCapability";

/**
 * Smooth scroll (Lenis) wired into a single RAF that also feeds the shared
 * scroll signal. A window pointermove listener feeds normalized cursor coords.
 * Under reduced-motion we skip Lenis entirely and fall back to native scroll,
 * still publishing progress for any consumers.
 */
export function useLenis(): void {
  useEffect(() => {
    const reduced = prefersReducedMotion();
    const cleanups: Array<() => void> = [];

    if (!reduced) {
      const lenis = new Lenis({ duration: 1.1, smoothWheel: true });
      lenis.on("scroll", (e: { progress?: number; velocity?: number }) => {
        setScroll(e.progress ?? 0, e.velocity ?? 0);
      });
      let rafId = 0;
      const raf = (time: number) => {
        lenis.raf(time);
        rafId = requestAnimationFrame(raf);
      };
      rafId = requestAnimationFrame(raf);
      cleanups.push(() => {
        cancelAnimationFrame(rafId);
        lenis.destroy();
      });
    } else {
      const onScroll = () => {
        const max =
          document.documentElement.scrollHeight - window.innerHeight;
        setScroll(max > 0 ? window.scrollY / max : 0);
      };
      window.addEventListener("scroll", onScroll, { passive: true });
      onScroll();
      cleanups.push(() => window.removeEventListener("scroll", onScroll));
    }

    if (!reduced && window.matchMedia("(pointer: fine)").matches) {
      const onPointer = (e: PointerEvent) => {
        setPointer(
          (e.clientX / window.innerWidth) * 2 - 1,
          (e.clientY / window.innerHeight) * 2 - 1,
        );
      };
      window.addEventListener("pointermove", onPointer, { passive: true });
      cleanups.push(() =>
        window.removeEventListener("pointermove", onPointer),
      );
    }

    return () => cleanups.forEach((fn) => fn());
  }, []);
}
