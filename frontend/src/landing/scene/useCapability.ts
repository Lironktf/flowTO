import { useEffect, useState } from "react";

/** True when the user asked the OS to minimize motion. */
export function prefersReducedMotion(): boolean {
  return (
    typeof window !== "undefined" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches
  );
}

/**
 * Whether we should mount live WebGL 3D. Desktop + fine pointer + not
 * reduced-motion + a working WebGL context. Phones / reduced-motion get a
 * static poster instead (and never download the GLBs or the three.js chunk).
 */
export function canRender3D(): boolean {
  if (typeof window === "undefined") return false;
  if (prefersReducedMotion()) return false;
  if (!window.matchMedia("(min-width: 768px) and (pointer: fine)").matches) {
    return false;
  }
  try {
    const c = document.createElement("canvas");
    return !!(
      c.getContext("webgl2") ||
      c.getContext("webgl") ||
      c.getContext("experimental-webgl")
    );
  } catch {
    return false;
  }
}

/** CSR-safe hook: resolves the capability check after mount. */
export function useCan3D(): boolean {
  const [ok, setOk] = useState(false);
  useEffect(() => {
    setOk(canRender3D());
  }, []);
  return ok;
}
