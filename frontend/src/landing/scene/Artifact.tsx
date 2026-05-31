import { lazy, Suspense, useEffect, useRef, useState } from "react";
import { useCan3D } from "./useCapability";
import { Poster } from "../ui/Poster";

const HeroScene = lazy(() => import("./HeroScene"));
const TrophyScene = lazy(() => import("./TrophyScene"));

interface Props {
  /** "tower" = hero (eager), "trophy" = below-fold (IntersectionObserver-gated). */
  kind: "tower" | "trophy";
  /** Gate mounting on viewport proximity (defer the heavy GLB fetch). */
  gate?: boolean;
}

/**
 * Capability + visibility gate around a lazy 3D canvas. Renders a CSS/SVG
 * Poster on mobile / reduced-motion / before-in-view, and only mounts WebGL
 * when the device can handle it AND the section is near the viewport.
 */
export function Artifact({ kind, gate = false }: Props) {
  const can3d = useCan3D();
  const ref = useRef<HTMLDivElement>(null);
  const [inView, setInView] = useState(!gate);

  useEffect(() => {
    if (!gate || inView || !ref.current) return;
    const io = new IntersectionObserver(
      (entries) => {
        if (entries[0]?.isIntersecting) {
          setInView(true);
          io.disconnect();
        }
      },
      { rootMargin: "250px" },
    );
    io.observe(ref.current);
    return () => io.disconnect();
  }, [gate, inView]);

  const Scene = kind === "tower" ? HeroScene : TrophyScene;
  const show3d = can3d && inView;

  return (
    <div ref={ref} className="stage-fill">
      {show3d ? (
        <Suspense fallback={<Poster variant={kind} />}>
          <Scene />
        </Suspense>
      ) : (
        <Poster variant={kind} />
      )}
    </div>
  );
}
