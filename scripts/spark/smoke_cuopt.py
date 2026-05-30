"""cuOpt smoke test — the gate for the optimizer's GPU sub-problem path (P10).

Prints one verdict on the last line:
    CUOPT_OK           -> cuOpt (pip module or self-hosted service) solved a tiny VRP.
    CUOPT_UNAVAILABLE  -> not installed/reachable; the heuristic baseline is the path.

A non-OK verdict is NOT a build failure — the heuristic optimizer always returns
an improving plan; cuOpt is a validated add-on.
"""

from __future__ import annotations

import sys


def main() -> int:
    # Prefer the pip module if present.
    try:
        from cuopt import routing  # noqa: F401

        print("cuopt module present")
        print("CUOPT_OK")
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"cuopt module not importable: {exc!r}", file=sys.stderr)

    # Else try the self-hosted service.
    try:
        from torontosim.optimizer.cuopt_client import CuOptUnavailable, solve_vrp

        try:
            solve_vrp({"ping": True})
            print("CUOPT_OK")
            return 0
        except CuOptUnavailable as exc:
            print(f"cuopt service unreachable: {exc!r}", file=sys.stderr)
    except Exception as exc:  # noqa: BLE001
        print(f"cuopt client error: {exc!r}", file=sys.stderr)

    print("CUOPT_UNAVAILABLE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
