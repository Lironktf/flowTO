import { useState } from "react";
import { COPILOT_CHIPS } from "../config";
import { useAppStore } from "../state/appStore";

export function CopilotPanel() {
  const log = useAppStore((s) => s.copilotLog);
  const send = useAppStore((s) => s.copilotSend);
  const [text, setText] = useState("");

  const submit = (value: string) => {
    if (!value.trim()) return;
    void send(value.trim());
    setText("");
  };

  return (
    <div className="panel copilot">
      <div className="eyebrow">Copilot · Nemotron · on-device</div>
      <div className="cop-log">
        {log.length === 0 && (
          <div className="msg bot">
            Ask me to ease congestion or test a closure — I preview every action and cite the bylaw
            constraints first.
          </div>
        )}
        {log.map((m, i) => (
          <div key={i} className={`msg ${m.role}`}>
            <div>{m.text}</div>
            {m.citations?.map((c, j) => (
              <div className="cite" key={j}>
                § {c.ref} — {c.note}
              </div>
            ))}
          </div>
        ))}
      </div>
      <div className="chips">
        {COPILOT_CHIPS.map((c) => (
          <button key={c} className="chip-btn" onClick={() => submit(c)}>
            {c}
          </button>
        ))}
      </div>
      <div className="cop-input">
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && submit(text)}
          placeholder="Ask the copilot…"
        />
        <button className="btn primary" onClick={() => submit(text)}>
          Send
        </button>
      </div>
    </div>
  );
}
