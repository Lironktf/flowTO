import { useEffect } from "react";
import { TOOLS } from "../config";
import { useAppStore } from "../state/appStore";
import { Icon, type IconKey } from "./Icons";

const TOOL_ICON: Record<string, IconKey> = {
  closure: "closure",
  lane: "lane",
  oneway: "oneway",
  signal: "signal",
  surge: "surge",
};

export function ToolRail() {
  const view = useAppStore((s) => s.view);
  const activeTool = useAppStore((s) => s.activeTool);
  const selectTool = useAppStore((s) => s.selectTool);

  // Keyboard: 1–5 select interventions; Esc → Select (Edit only).
  useEffect(() => {
    if (view !== "edit") return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") selectTool("select");
      const n = Number(e.key);
      if (n >= 1 && n <= TOOLS.length) selectTool(TOOLS[n - 1].id);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [view, selectTool]);

  return (
    <>
      <button
        className={`rail-tool ${activeTool === "select" ? "active" : ""}`}
        onClick={() => selectTool("select")}
      >
        <Icon.select />
        <span className="rail-tip">Select · Esc</span>
      </button>
      <div className="rail-sep" />
      {TOOLS.map((t, i) => {
        const I = Icon[TOOL_ICON[t.id]];
        return (
          <button
            key={t.id}
            className={`rail-tool ${activeTool === t.id ? "active" : ""}`}
            onClick={() => selectTool(t.id)}
          >
            <I />
            <span className="rail-tip">
              {t.name} · {i + 1}
            </span>
          </button>
        );
      })}
    </>
  );
}
