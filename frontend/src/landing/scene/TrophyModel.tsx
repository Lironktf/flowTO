import { useMemo, useRef } from "react";
import { useFrame } from "@react-three/fiber";
import { Group, MeshStandardMaterial } from "three";
import { useNormalized } from "./modelUtils";
import { scrollSignal } from "../scroll/scrollStore";

const URL = "/models/worldcup.glb";

/**
 * The FIFA World Cup trophy (scenario artifact). Lazy + IntersectionObserver
 * gated by the caller. The source GLB's long axis is Z, so an inner group tilts
 * it upright (Z→Y); the outer `spin` group carries a gentle vertical spin + bob
 * and a tightly clamped tilt so it never rolls fully sideways. Material is a
 * gleaming gold metal that catches the environment lightformers.
 */
export function TrophyModel() {
  const spin = useRef<Group>(null);
  const material = useMemo(
    () =>
      new MeshStandardMaterial({
        color: "#e8c66a",
        metalness: 1.0,
        roughness: 0.25,
        emissive: "#3a2c08",
        emissiveIntensity: 0.35,
      }),
    [],
  );
  const { obj, scale } = useNormalized(URL, 8, material);

  useFrame((state) => {
    const g = spin.current;
    if (!g) return;
    const t = state.clock.elapsedTime;
    const { pointerX, pointerY } = scrollSignal;
    // Continuous gentle spin about the vertical axis + small pointer steer.
    g.rotation.y = t * 0.18 + pointerX * 0.35;
    // Tilt is clamped to ±0.1 rad so the trophy never lies down; Z stays 0.
    g.rotation.x = Math.max(-0.1, Math.min(0.1, pointerY * 0.08));
    g.rotation.z = 0;
    g.position.y = Math.sin(t * 0.5) * 0.12;
  });

  return (
    <group ref={spin}>
      <group rotation={[-Math.PI / 2, 0, 0]}>
        <group scale={scale}>
          <primitive object={obj} />
        </group>
      </group>
    </group>
  );
}

// NOTE: deliberately NOT preloaded — only fetched when its section nears view.
