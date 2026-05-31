import { Badge } from "../ui/Badge";
import { Reveal } from "../ui/Reveal";

const STEPS = [
  {
    title: "Make a change",
    body: "Close a street, add a route, or retime a signal — right on the map.",
  },
  {
    title: "See the ripple",
    body: "flowTO instantly shows where traffic eases and where it backs up.",
  },
  {
    title: "Compare & decide",
    body: "Weigh travel times and delays before vs. after, and pick the plan that works.",
  },
];

export function HowItWorks() {
  return (
    <section className="section" id="how">
      <div className="container">
        <div className="sec-head sec-head--center">
          <Badge>How it works</Badge>
          <h2 className="h2">Three steps from question to answer.</h2>
        </div>
        <Reveal>
          <div className="steps">
            {STEPS.map((s, i) => (
              <div className="step" key={s.title}>
                <div className="step__num">{i + 1}</div>
                <h3 className="h3 step__title">{s.title}</h3>
                <p className="engine-card__body">{s.body}</p>
              </div>
            ))}
          </div>
        </Reveal>
      </div>
    </section>
  );
}
