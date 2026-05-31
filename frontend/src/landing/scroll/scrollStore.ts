/**
 * Standalone scroll + pointer signal shared by the r3f render loop (read inside
 * useFrame — NO React re-renders) and any DOM consumers. Deliberately a plain
 * mutable singleton, NOT the app's zustand store, to keep the landing isolated.
 */
export const scrollSignal = {
  progress: 0, // 0..1 over the whole document
  velocity: 0, // lenis scroll velocity
  pointerX: 0, // -1..1, normalized cursor position
  pointerY: 0, // -1..1
};

export function setScroll(progress: number, velocity = 0): void {
  scrollSignal.progress = progress;
  scrollSignal.velocity = velocity;
}

export function setPointer(x: number, y: number): void {
  scrollSignal.pointerX = x;
  scrollSignal.pointerY = y;
}
