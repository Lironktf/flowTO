import { Canvas } from "@react-three/fiber";
import { Suspense } from "react";
import { Environment, Lightformer } from "@react-three/drei";
import { TrophyModel } from "./TrophyModel";

/** Lazy-loaded scenario canvas (FIFA trophy). Default export → React.lazy. */
export default function TrophyScene() {
  return (
    <Canvas
      dpr={[1, 1.75]}
      camera={{ position: [0, 1.5, 12], fov: 42 }}
      gl={{ antialias: true, alpha: true, powerPreference: "high-performance" }}
      style={{ background: "transparent" }}
    >
      <ambientLight intensity={0.5} />
      <directionalLight position={[6, 10, 4]} intensity={2.6} color="#fff6e0" />
      <directionalLight position={[-6, 4, -6]} intensity={0.8} color="#6f9bff" />
      {/* Inline lightformer studio (no preset → fully offline) so the gold
          metal actually gleams with warm reflections. */}
      <Environment resolution={256} frames={1}>
        <Lightformer
          form="rect"
          intensity={5}
          color="#fff6e0"
          position={[4, 5, 4]}
          scale={[7, 7, 1]}
        />
        <Lightformer
          form="rect"
          intensity={3}
          color="#ffd86b"
          position={[-4, 2, 3]}
          scale={[5, 6, 1]}
        />
        <Lightformer
          form="rect"
          intensity={2}
          color="#6f9bff"
          position={[0, -2, -5]}
          scale={[8, 4, 1]}
        />
      </Environment>
      <Suspense fallback={null}>
        <TrophyModel />
      </Suspense>
    </Canvas>
  );
}
