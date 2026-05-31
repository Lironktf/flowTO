#!/usr/bin/env python3
"""Run bench_cudf_pandas.py twice — stock pandas vs the `cudf.pandas`
zero-code-change accelerator — and print the side-by-side comparison.

    .venv/bin/python benchmarks/run_cudf_pandas.py --repeats 3

Both passes execute the SAME script (same `import pandas as pd` code); the only
difference is the second runs under `python -m cudf.pandas`, which patches
pandas to run on the GPU with automatic CPU fallback. This shows what each
call-site gains with no code rewrite — contrast with run_all.py, which uses the
explicit cuDF API.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys

_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bench_cudf_pandas.py")


def _run(cmd):
    print(f"\n$ {' '.join(cmd)}")
    proc = subprocess.run(cmd, capture_output=True, text=True)
    # surface the human-readable table; drop RESULT lines + cuDF import noise
    for line in proc.stdout.splitlines():
        if not line.startswith("RESULT\t"):
            print(line)
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr[-2000:])
        raise SystemExit(f"subprocess failed: {' '.join(cmd)}")
    results = {}
    for line in proc.stdout.splitlines():
        if line.startswith("RESULT\t"):
            _, _mode, title, ms = line.split("\t")
            results[title] = float(ms)
    return results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repeats", type=int, default=3)
    args = ap.parse_args()
    rp = ["--repeats", str(args.repeats)]
    py = sys.executable

    cpu = _run([py, _SCRIPT, *rp])
    gpu = _run([py, "-m", "cudf.pandas", _SCRIPT, *rp])

    print(f"\n{'=' * 84}\n COMPARISON: stock pandas vs cudf.pandas (zero code change)\n{'=' * 84}")
    print(f"{'location':<52}{'pandas':>9}{'cudf.pandas':>13}{'speedup':>9}")
    print("-" * 84)
    for title in cpu:
        c, g = cpu[title], gpu.get(title, float("nan"))
        loc = title.split("(")[0].strip()
        if len(loc) > 50:
            loc = loc[:49] + "…"
        print(f"{loc:<52}{c:8.1f}ms{g:11.1f}ms{c / g:8.1f}x")


if __name__ == "__main__":
    main()
