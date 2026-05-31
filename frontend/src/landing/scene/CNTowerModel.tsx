import { useMemo, useRef } from "react";
import { useFrame } from "@react-three/fiber";
import { Group, MeshStandardMaterial } from "three";
import { useNormalized, preloadModel } from "./modelUtils";
import { scrollSignal } from "../scroll/scrollStore";

const URL = "/models/cn-tower.glb";

/**
 * Hero artifact. The source model's long axis is Z; we tilt it upright (Z→Y),
 * then a parent group carries a gentle oscillation + pointer/scroll parallax so
 * the recognizable ¾ profile stays toward the camera. The body is a clean gray
 * metal that reads as a sculptural silhouette against the near-black ground.
 */
export function CNTowerModel() {
  const spin = useRef<Group>(null);

  const material = useMemo(
    () =>
      new MeshStandardMaterial({
        color: "#aab0b8",
        metalness: 0.55,
        roughness: 0.4,
      }),
    [],
  );

  const { obj, scale } = useNormalized(URL, 7.4, material);

  useFrame((state) => {
    const g = spin.current;
    if (!g) return;
    const t = state.clock.elapsedTime;
    const { pointerX, pointerY, progress } = scrollSignal;
    // Gentle oscillation instead of a continuous full spin — keeps the ¾ face
    // toward the camera while still feeling alive.
    g.rotation.y = Math.sin(t * 0.15) * 0.5 + pointerX * 0.5;
    g.rotation.x = pointerY * 0.08 + progress * 0.15;
    g.rotation.z = pointerX * 0.03;
    g.position.y = Math.sin(t * 0.55) * 0.18;
    g.position.x = pointerX * 0.25;
  });

  return (
    <group ref={spin}>
      {/* taller tower, lifted up so the antenna sits high in the hero while the
          (bigger) base still reaches down into the Numbers band */}
      <group position={[0, -0.4, 0]} rotation={[-Math.PI / 2, 0, 0]}>
        <group scale={scale}>
          <primitive object={obj} />
        </group>
      </group>
    </group>
  );
}

preloadModel(URL);
