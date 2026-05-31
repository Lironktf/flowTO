import { useEffect, useRef, useState } from "react";
import { useAppStore } from "../state/appStore";
import { Icon } from "./Icons";

const fmtDelta = (v: number) => (v > 0 ? `+${v}` : `${v}`);
const DELTA_ROWS: [string, string][] = [
  ["high_risk_edges", "high-risk"],
  ["severe_edges", "severe"],
];

/** Suggestion chips — graph-grounded prompts from the store (static fallback). */
function ChipRow({ disabled, onPick }: { disabled: boolean; onPick: (c: string) => void }) {
  const chips = useAppStore((s) => s.copilotChips);
  return (
    <>
      {chips.map((c) => (
        <button key={c} className="chip" disabled={disabled} onClick={() => onPick(c)}>
          {c}
        </button>
      ))}
    </>
  );
}

export function CopilotRegion() {
  const log = useAppStore((s) => s.copilotLog);
  const ask = useAppStore((s) => s.copilotAsk);
  const confirm = useAppStore((s) => s.copilotConfirm);
  const revert = useAppStore((s) => s.copilotRevert);
  const deepMode = useAppStore((s) => s.deepMode);
  const toggleDeep = useAppStore((s) => s.toggleDeep);
  const stop = useAppStore((s) => s.copilotStop);
  const latency = useAppStore((s) => s.copilotLatency);
  const thinking = useAppStore((s) => s.copilotThinking);
  const pendingMode = useAppStore((s) => s.copilotPendingMode);
  const ready = useAppStore((s) => s.copilotReady);
  // One loader; only the label changes with the resolved mode.
  const thinkLabel =
    pendingMode === "agent"
      ? "investigating…"
      : pendingMode === "chat"
        ? "responding…"
        : "thinking…";
  const [text, setText] = useState("");

  const logRef = useRef<HTMLDivElement>(null);
  // Auto-scroll to the newest message (and as a stream grows).
  useEffect(() => {
    const el = logRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [log, thinking]);

  // Thinking bubble only before a bot reply has started (streaming supersedes it).
  const showThinking = thinking && (log.length === 0 || log[log.length - 1].role === "user");

  const busy = thinking || !ready;
  const submit = (value: string) => {
    if (!value.trim() || busy) return;
    void ask(value.trim());
    setText("");
  };

  return (
    <section className="region grow" id="copilot-region">
      <div className="region-hd">
        <span className="lbl copilot-title">Copilot · Nemotron</span>
        <button
          className={`mode-tab deep-toggle ${deepMode ? "active" : ""}`}
          aria-pressed={deepMode}
          title="Deep: let Nemotron investigate (simulate / optimize) before it proposes. Off: quick answer or a single action."
          onClick={toggleDeep}
        >
          🧠 Deep {deepMode ? "on" : "off"}
        </button>
      </div>
      {latency && (
        <div className="copilot-latbar">
          ⏱ {(latency.ms / 1000).toFixed(1)}s
          {latency.firstTokenMs != null ? ` · first ${latency.firstTokenMs}ms` : ""}
          {` · ${latency.mode}`}
        </div>
      )}
      <div className={`copilot-log ${log.length === 0 ? "empty" : ""}`} ref={logRef}>
        {log.length === 0 && (
          <div className="copilot-welcome">
            <span className="who">Copilot</span>
            <div className="bub">
              Ask me to ease congestion or test a closure — I preview every action and cite the bylaw
              constraints first.
            </div>
            <div className="copilot-welcome-chips">
              <ChipRow disabled={busy} onPick={submit} />
            </div>
          </div>
        )}
        {log.map((m, i) => (
          <div key={i} className={`msg ${m.role}`}>
            <span className="who">
              {m.role === "user" ? "You" : "Copilot"}
              {m.role === "bot" && m.mode ? <span className="mode-badge">{m.mode}</span> : null}
            </span>
            <div className="bub">
              {m.text}
              {m.aborted && <span className="aborted-tag"> (stopped)</span>}
              {m.agentSteps && m.agentSteps.length > 0 && (
                <details className="agent-trace-wrap">
                  <summary>Show reasoning · {m.agentSteps.length} steps</summary>
                  <ol className="agent-trace">
                    {m.agentSteps.map((s, j) => (
                      <li key={j}>
                        <span className="ref">{s.tool}</span>
                        {s.thought ? <span className="thought"> — {s.thought}</span> : null}
                      </li>
                    ))}
                  </ol>
                </details>
              )}
              {m.steps && m.steps.length > 0 && (
                <ul className="plan-steps">
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
                <div className="copilot-confirm">
                  <button className="btn primary" disabled={m.applied} onClick={() => void confirm(i)}>
                    {m.applied
                      ? "✓ Applied"
                      : `Confirm & run (${m.interventions.length} change${
                          m.interventions.length > 1 ? "s" : ""
                        })`}
                  </button>
                </div>
              )}
              {m.result && (
                <div className="result-card">
                  <div className="metric-row">
                    {typeof m.result.summaryDelta.average_pressure === "number" && (
                      <span className="metric">
                        pressure {m.result.summaryDelta.average_pressure <= 0 ? "▼" : "▲"}
                        {Math.abs(m.result.summaryDelta.average_pressure).toFixed(3)}
                      </span>
                    )}
                    {DELTA_ROWS.map(([k, label]) =>
                      m.result!.summaryDelta[k] ? (
                        <span key={k} className="metric">
                          {label} {fmtDelta(m.result!.summaryDelta[k])}
                        </span>
                      ) : null,
                    )}
                  </div>
                  {m.result.mostImpacted.length > 0 && (
                    <div className="impacted">
                      Most affected:{" "}
                      {m.result.mostImpacted
                        .slice(0, 3)
                        .map((e) => e.road_name || e.edge_id)
                        .join(", ")}
                    </div>
                  )}
                  {m.reverted ? (
                    <span className="aborted-tag">↩ reverted to baseline</span>
                  ) : (
                    <button className="btn ghost revert-btn" onClick={() => void revert(i)}>
                      ↩ Revert to baseline
                    </button>
                  )}
                </div>
              )}
            </div>
          </div>
        ))}
        {showThinking && (
          <div className="msg bot">
            <span className="who">Copilot</span>
            <div className="bub copilot-thinking">
              <span className="dot" />
              <span className="dot" />
              <span className="dot" />
              <span className="think-label">{thinkLabel}</span>
            </div>
          </div>
        )}
      </div>
      {!ready && (
        <div className="copilot-warming">
          <span className="dot" />
          warming the twin… (priming the baseline)
        </div>
      )}
      {log.length > 0 && (
        <div className="copilot-chips">
          <ChipRow disabled={busy} onPick={submit} />
        </div>
      )}
      <div className="copilot-input">
        <input
          value={text}
          disabled={busy}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && submit(text)}
          placeholder={!ready ? "Warming the twin…" : thinking ? "Working…" : "Ask in plain English…"}
        />
        {thinking ? (
          <button className="btn copilot-send copilot-stop" onClick={stop} aria-label="Stop" title="Stop">
            ■
          </button>
        ) : (
          <button
            className="btn primary copilot-send"
            onClick={() => submit(text)}
            disabled={!ready}
            aria-label="Send"
          >
            <Icon.send />
          </button>
        )}
      </div>
    </section>
  );
}
