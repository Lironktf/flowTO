import { useState } from "react";
import { COPILOT_CHIPS } from "../config";
import { useAppStore } from "../state/appStore";
import { Icon } from "./Icons";

export function CopilotRegion() {
  const log = useAppStore((s) => s.copilotLog);
  const ask = useAppStore((s) => s.copilotAsk);
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
