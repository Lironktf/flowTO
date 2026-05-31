"""Side-by-side A/B comparison + report rendering.

Takes ``{config_name: {metric: value}}`` and produces a comparison that names the
winner per metric (lower-is-better for errors, higher-is-better for r²/accuracy/
overlap) and the delta of each config vs a reference config (default ``baseline``).
Emits ``benchmark_report.{json,md}``.
"""

from __future__ import annotations

import json
from pathlib import Path

# Metrics where a HIGHER value is better; everything else is lower-is-better.
HIGHER_IS_BETTER = {"r2", "risk_accuracy"}


def _higher_better(metric: str) -> bool:
    return metric in HIGHER_IS_BETTER or "overlap" in metric or "accuracy" in metric


def compare_configs(
    results: dict[str, dict[str, float]], reference: str = "baseline"
) -> dict:
    """Build a comparison structure: per-metric winner + per-config deltas vs ref.

    ``results`` maps config → metric dict. Configs need not share every metric; a
    metric is compared only across the configs that report it.
    """
    if reference not in results:
        # fall back to the first config if the named reference is absent
        reference = next(iter(results))
    metrics = sorted({m for d in results.values() for m in d})

    per_metric: dict[str, dict] = {}
    for metric in metrics:
        scored = {c: d[metric] for c, d in results.items() if metric in d}
        if not scored:
            continue
        pick = max if _higher_better(metric) else min
        winner = pick(scored, key=scored.get)
        ref_val = results.get(reference, {}).get(metric)
        deltas = (
            {c: v - ref_val for c, v in scored.items()} if ref_val is not None else {}
        )
        per_metric[metric] = {
            "values": scored,
            "winner": winner,
            "higher_is_better": _higher_better(metric),
            "delta_vs_reference": deltas,
        }

    return {
        "reference": reference,
        "configs": sorted(results),
        "metrics": per_metric,
    }


def render_markdown(comparison: dict) -> str:
    """Render the comparison as a Markdown table (config × metric, winner marked)."""
    configs = comparison["configs"]
    metrics = list(comparison["metrics"])
    lines = [
        f"# GNN benchmark — reference: `{comparison['reference']}`",
        "",
        "| metric | " + " | ".join(f"`{c}`" for c in configs) + " | winner |",
        "|" + "---|" * (len(configs) + 2),
    ]
    for metric in metrics:
        m = comparison["metrics"][metric]
        cells = []
        for c in configs:
            if c in m["values"]:
                mark = " ✅" if c == m["winner"] else ""
                cells.append(f"{m['values'][c]:.4f}{mark}")
            else:
                cells.append("—")
        arrow = "↑" if m["higher_is_better"] else "↓"
        lines.append(f"| {metric} {arrow} | " + " | ".join(cells) + f" | `{m['winner']}` |")
    return "\n".join(lines) + "\n"


def write_report(
    comparison: dict, json_path: str | Path, md_path: str | Path
) -> None:
    json_path, md_path = Path(json_path), Path(md_path)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(comparison, indent=2, sort_keys=True))
    md_path.write_text(render_markdown(comparison))
