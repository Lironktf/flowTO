"""GPU smoke test: prove we can run a parallel kernel on the GB10 from Python via NVIDIA Warp."""
import warp as wp

wp.init()
print("Warp version:", wp.config.version if hasattr(wp.config, "version") else "?")
print("Devices:", wp.get_devices())

N = 5_000_000


@wp.kernel
def fill(x: wp.array(dtype=wp.float32)):
    i = wp.tid()
    x[i] = float(i) * 2.0


a = wp.zeros(N, dtype=wp.float32, device="cuda")
wp.launch(fill, dim=N, inputs=[a], device="cuda")
wp.synchronize()
host = a.numpy()
print(f"Launched {N:,}-element kernel on CUDA. a[-1]={host[-1]} (expected {2.0*(N-1)})")
print("GPU compute from Python: OK" if host[-1] == 2.0 * (N - 1) else "MISMATCH")
