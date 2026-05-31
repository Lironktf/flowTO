import { CountUp } from "../ui/CountUp";
import { Reveal } from "../ui/Reveal";

const STATS: Array<{ node: JSX.Element; label: string }> = [
  {
    node: <CountUp to={100} suffix="%" />,
    label: "of Toronto's streets + transit, modeled",
  },
  {
    node: <span className="num--word">Seconds</span>,
    label: "to see any change's full impact",
  },
  {
    node: <span className="num--word">Before / after</span>,
    label: "every option, compared side by side",
  },
  { node: <CountUp to={0} />, label: "data ever leaves your building" },
];

export function Numbers() {
  return (
    <section className="section--tight numbers-band">
      <div className="container">
        <Reveal>
          <div className="numbers">
            {STATS.map((s) => (
              <div className="numbers__cell" key={s.label}>
                <div className="num flow-text">{s.node}</div>
                <div className="numbers__label">{s.label}</div>
              </div>
            ))}
          </div>
        </Reveal>
      </div>
    </section>
  );
}
