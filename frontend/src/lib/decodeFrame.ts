/**
 * Decode the backend's binary tick frame (P06 api.encoding):
 *   [count: u32][edge_idx: u32, load: f32, speed: f32, pressure: f32, closure: u8] × count
 * little-endian, 17 bytes/record. Writes in place into the tick store typed
 * arrays — never touches React state.
 */
export const RECORD_SIZE = 17;

export interface TickArrays {
  load: Float32Array;
  speed: Float32Array;
  pressure: Float32Array;
  closure: Uint8Array;
}

export function makeTickArrays(n: number): TickArrays {
  return {
    load: new Float32Array(n),
    speed: new Float32Array(n),
    pressure: new Float32Array(n),
    closure: new Uint8Array(n),
  };
}

/** Decode a frame buffer into `arrays` (indexed by edge_idx). Returns #records. */
export function decodeFrameInto(buffer: ArrayBuffer, arrays: TickArrays): number {
  const dv = new DataView(buffer);
  const count = dv.getUint32(0, true);
  let off = 4;
  for (let i = 0; i < count; i++) {
    const idx = dv.getUint32(off, true);
    const load = dv.getFloat32(off + 4, true);
    const speed = dv.getFloat32(off + 8, true);
    const pressure = dv.getFloat32(off + 12, true);
    const closure = dv.getUint8(off + 16);
    off += RECORD_SIZE;
    if (idx < arrays.pressure.length) {
      arrays.load[idx] = load;
      arrays.speed[idx] = speed;
      arrays.pressure[idx] = pressure;
      arrays.closure[idx] = closure;
    }
  }
  return count;
}
