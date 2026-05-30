import { useState } from "react";
import { COPILOT_CHIPS } from "../config";
import { useAppStore } from "../state/appStore";
import { Icon } from "./Icons";

export function CopilotRegion() {
  const log = useAppStore((s) => s.copilotLog);
  const ask = useAppStore((s) => s.copilotAsk);
  const confirm = useAppStore((s) => s.copilotConfirm);
  const agentMode = useAppStore((s) => s.agentMode);
  const toggleAgentMode = useAppStore((s) => s.toggleAgentMode);
  const latency = useAppStore((s) => s.copilotLatency);
  const [text, setText] = useState("");

  const submit = (value: string) => {
    if (!value.trim()) return;
    void ask(value.trim());
    setText("");
  };

  return (
    <section className="region grow" id="copilot-region">
      <div className="region-hd">
        <span className="lbl">Copilot · Nemotron · on-device</span>
        <span className="copilot-hud" style={{ marginLeft: "auto", display: "flex", gap: 10, alignItems: "center" }}>
          {latency && (
            <span className="lat" title="last copilot call" style={{ opacity: 0.7, fontVariantNumeric: "tabular-nums" }}>
              ⏱ {(latency.ms / 1000).toFixed(1)}s
              {latency.firstTokenMs != null ? ` · first ${latency.firstTokenMs}ms` : ""}
              {` · ${latency.mode}`}
            </span>
          )}
          <button
            className={`chip ${agentMode ? "active" : ""}`}
            aria-pressed={agentMode}
            onClick={toggleAgentMode}
            title="Let Nemotron chain tools (investigate → propose) before recommending"
          >
            🧠 Agent {agentMode ? "on" : "off"}
          </button>
        </span>
      </div>
      <div className="copilot-log">
        {log.length === 0 && (
          <div className="msg bot">
            <span className="who">Copilot</span>
            <div className="bub">
              Ask me to ease congestion or test a closure — I preview every action and cite the bylaw
              constraints first.
            </div>
          </div>
        )}
        {log.map((m, i) => (
          <div key={i} className={`msg ${m.role}`}>
            <span className="who">{m.role === "user" ? "You" : "Copilot"}</span>
            <div className="bub">
              {m.text}
              {m.streaming && <span className="stream-cursor" aria-hidden>▍</span>}
              {m.agentSteps && m.agentSteps.length > 0 && (
                <ol className="agent-trace" style={{ margin: "6px 0 0", paddingLeft: 18, opacity: 0.8 }}>
                  {m.agentSteps.map((s, j) => (
                    <li key={j}>
                      <span className="ref">{s.tool}</span>
                    </li>
                  ))}
                </ol>
              )}
              {m.steps && m.steps.length > 0 && (
                <ul style={{ margin: "6px 0 0", paddingLeft: 16 }}>
                  {m.steps.map((s, j) => (
                    <li key={j}>{s}</li>
                  ))}
                </ul>
              )}
              {m.citations && m.citations.length > 0 && (
                <div className="cite">
                  {m.citations.map((c, j) => (
                    <span key={j}>
                      <span className="ref">{c.ref}</span> — {c.note}
                    </span>
                  ))}
                </div>
              )}
              {m.interventions && m.interventions.length > 0 && (
                <div className="copilot-confirm" style={{ marginTop: 8 }}>
                  <button
                    className="btn primary"
                    disabled={m.applied}
                    onClick={() => void confirm(i)}
                  >
                    {m.applied
                      ? "✓ Applied"
                      : `Confirm & run (${m.interventions.length} change${
                          m.interventions.length > 1 ? "s" : ""
                        })`}
                  </button>
                </div>
              )}
            </div>
          </div>
        ))}
      </div>
      <div className="copilot-chips">
        {COPILOT_CHIPS.map((c) => (
          <button key={c} className="chip" onClick={() => submit(c)}>
            {c}
          </button>
        ))}
      </div>
      <div className="copilot-input">
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && submit(text)}
          placeholder="Ask in plain English…"
        />
        <button className="btn primary copilot-send" onClick={() => submit(text)} aria-label="Send">
          <Icon.send />
        </button>
      </div>
    </section>
  );
}
