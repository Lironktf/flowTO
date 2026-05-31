import { useMemo } from "react";
import { Box3, Material, Object3D, Vector3 } from "three";
import { useGLTF } from "@react-three/drei";

const DRACO_PATH = "/draco/";

export interface Normalized {
  obj: Object3D;
  scale: number;
}

/**
 * Load a Draco-compressed GLB, clone it (StrictMode-safe — the cached scene
 * can't be mounted twice), center its bounding box at the origin, and compute
 * a scale that fits its largest dimension to `targetSize`. Optionally override
 * every mesh material (used to give the artifacts a uniform sculptural look
 * regardless of their source textures).
 */
export function useNormalized(
  url: string,
  targetSize: number,
  material?: Material,
): Normalized {
  const { scene } = useGLTF(url, DRACO_PATH);
  return useMemo(() => {
    const obj = scene.clone(true);
    if (material) {
      obj.traverse((o) => {
        const mesh = o as { isMesh?: boolean; material?: Material };
        if (mesh.isMesh) mesh.material = material;
      });
    }
    const box = new Box3().setFromObject(obj);
    const size = new Vector3();
    const center = new Vector3();
    box.getSize(size);
    box.getCenter(center);
    const maxDim = Math.max(size.x, size.y, size.z) || 1;
    obj.position.set(-center.x, -center.y, -center.z);
    return { obj, scale: targetSize / maxDim };
  }, [scene, targetSize, material]);
}

export function preloadModel(url: string): void {
  useGLTF.preload(url, DRACO_PATH);
}
