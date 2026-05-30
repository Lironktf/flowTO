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
        <span className="lbl" style={{ whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
          Copilot · Nemotron
        </span>
        <button
          className={`chip ${agentMode ? "active" : ""}`}
          aria-pressed={agentMode}
          onClick={toggleAgentMode}
          title="Let Nemotron chain tools (investigate → propose) before recommending"
          style={{ marginLeft: "auto", flex: "0 0 auto" }}
        >
          🧠 Agent {agentMode ? "on" : "off"}
        </button>
      </div>
      {latency && (
        <div
          className="copilot-latbar"
          style={{
            padding: "2px 10px",
            fontSize: 11,
            opacity: 0.6,
            fontVariantNumeric: "tabular-nums",
            borderBottom: "1px solid var(--hairline, #2b3440)",
          }}
        >
          ⏱ {(latency.ms / 1000).toFixed(1)}s
          {latency.firstTokenMs != null ? ` · first ${latency.firstTokenMs}ms` : ""}
          {` · ${latency.mode}`}
        </div>
      )}
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
                <ol className="agent-trace" style={{ margin: "6px 0 0", paddingLeft: 18, opacity: 0.85 }}>
                  {m.agentSteps.map((s, j) => (
                    <li key={j} style={{ marginBottom: 3 }}>
                      <span className="ref">{s.tool}</span>
                      {s.thought ? <span style={{ opacity: 0.75 }}> — {s.thought}</span> : null}
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
