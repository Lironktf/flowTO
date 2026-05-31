import { Canvas } from "@react-three/fiber";
import { Environment, Lightformer } from "@react-three/drei";
import { Suspense } from "react";
import { CNTowerModel } from "./CNTowerModel";

/** Lazy-loaded hero canvas (CN Tower). Default export → React.lazy target. */
export default function HeroScene() {
  return (
    <Canvas
      dpr={[1, 1.75]}
      camera={{ position: [0, -1.0, 9], fov: 40 }}
      gl={{ antialias: true, alpha: true, powerPreference: "high-performance" }}
      style={{ background: "transparent" }}
    >
      {/* Warm/white key for body shading + a soft cobalt fill. Kept low so the
          metal stays dark and only catches crisp specular streaks. */}
      <ambientLight intensity={0.4} />
      <directionalLight position={[5, 9, 6]} intensity={1.6} color="#ffffff" />
      <directionalLight position={[-7, 3, -5]} intensity={0.5} color="#6f9bff" />

      {/* Inline, offline IBL — narrow-ish rect panels wrap the tower so the
          dark metal always catches a specular streak no matter the rotation,
          without washing the whole surface to white. NO preset prop → no CDN. */}
      <Environment resolution={256} frames={1}>
        <Lightformer
          form="rect"
          intensity={1.5}
          color="#ffffff"
          position={[3, 3, 4]}
          scale={[2, 6, 1]}
        />
        <Lightformer
          form="rect"
          intensity={1.4}
          color="#eef2f6"
          position={[-4, 1, 2]}
          scale={[1.8, 6, 1]}
        />
        <Lightformer
          form="rect"
          intensity={0.9}
          color="#6f9bff"
          position={[0, -3, -4]}
          scale={[5, 2.5, 1]}
        />
        <Lightformer
          form="rect"
          intensity={1.1}
          color="#ffffff"
          position={[-3, 2, -5]}
          scale={[2, 7, 1]}
        />
      </Environment>

      <Suspense fallback={null}>
        <CNTowerModel />
      </Suspense>
    </Canvas>
  );
}
