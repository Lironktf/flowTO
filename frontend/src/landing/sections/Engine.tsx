import type { ReactNode } from "react";
import { Badge } from "../ui/Badge";
import { Reveal } from "../ui/Reveal";

const ICON = {
  stroke: "currentColor",
  strokeWidth: 1.6,
  fill: "none",
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
};

const CARDS: Array<{ icon: ReactNode; title: string; body: string }> = [
  {
    icon: (
      <svg viewBox="0 0 24 24" width="22" height="22" {...ICON}>
        <path d="M12 21s7-5.5 7-11a7 7 0 1 0-14 0c0 5.5 7 11 7 11z" />
        <circle cx="12" cy="10" r="2.5" />
      </svg>
    ),
    title: "Built on the real Toronto",
    body: "The city's actual streets and live transit schedules — TTC, GO and UP — not a simplified sketch.",
  },
  {
    icon: (
      <svg viewBox="0 0 24 24" width="22" height="22" {...ICON}>
        <circle cx="5" cy="6" r="2" />
        <circle cx="19" cy="6" r="2" />
        <circle cx="12" cy="18" r="2" />
        <path d="M6.6 7.3 10.6 16.5M17.4 7.3 13.4 16.5M7 6h10" />
      </svg>
    ),
    title: "Modeling you can stand behind",
    body: "Real-world traffic data is sparse and patchy. flowTO's modeling fills the gaps — turning the limited counts that exist into reliable, city-wide predictions you couldn't get any other way.",
  },
  {
    icon: (
      <svg viewBox="0 0 24 24" width="22" height="22" {...ICON}>
        <path d="M4 5h16v11H8l-4 3z" />
        <path d="M12 8.5 13 11l2.5 1-2.5 1-1 2.5-1-2.5L8.5 12l2.5-1z" />
      </svg>
    ),
    title: "Ask in plain language",
    body: "“What if we close Lake Shore eastbound for the match?” Get back a workable plan that respects local bylaws — with the rules it's based on, cited.",
  },
  {
    icon: (
      <svg viewBox="0 0 24 24" width="22" height="22" {...ICON}>
        <rect x="7" y="7" width="10" height="10" rx="1.5" />
        <path d="M10 7V4M14 7V4M10 20v-3M14 20v-3M7 10H4M7 14H4M20 10h-3M20 14h-3" />
      </svg>
    ),
    title: "Runs entirely on one machine",
    body: "No cloud, no internet, no IT project — the whole-city model runs locally and answers in real time. Use it in the office or in a command post on event day.",
  },
];

export function Engine() {
  return (
    <section className="section" id="engine">
      <div className="container">
        <div className="sec-head sec-head--center">
          <Badge>Built for decisions you can defend</Badge>
          <h2 className="h2">Evidence you can take to the table.</h2>
          <p className="body-l">
            Every result comes from the city's real network and proven traffic
            modeling — so you can stand behind the numbers, not just the picture.
          </p>
        </div>
        <Reveal>
          <div className="grid-4">
            {CARDS.map((c) => (
              <div className="card" key={c.title}>
                <div className="engine-card__icon">{c.icon}</div>
                <h3 className="h3 engine-card__title">{c.title}</h3>
                <p className="engine-card__body">{c.body}</p>
              </div>
            ))}
          </div>
        </Reveal>
      </div>
    </section>
  );
}
