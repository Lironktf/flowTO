import { Badge } from "../ui/Badge";
import { Button } from "../ui/Button";
import { Artifact } from "../scene/Artifact";
import { TransitBackdrop } from "../ui/TransitBackdrop";
import { APP_URL } from "../constants";

export function Hero() {
  return (
    <section className="hero">
      {/* Dimmed roads + TTC subway-line backdrop — signals "transit planner". */}
      <div className="hero__transit" aria-hidden="true">
        <TransitBackdrop />
      </div>
      <div
        className="glow"
        style={{ width: 560, height: 560, right: "-80px", top: "6%" }}
      />
      <div className="container hero__grid">
        <div className="hero__copy">
          <Badge>Traffic + transit planning</Badge>
          <h1 className="h1" style={{ marginTop: 22 }}>
            Toronto,
            <br />
            <span className="flow-text">Simulated</span>.
          </h1>
          <div className="hero__underline" />
          <p className="body-l hero__lede">
            See how any change to Toronto's streets and transit would play out —
            before you make it. Close a road, add a route, or plan for a major
            event, and watch the whole city respond in seconds.
          </p>
          <div className="hero__cta">
            <Button href={APP_URL} variant="primary">
              Open the simulation →
            </Button>
            <Button href="#scenario" variant="ghost">
              See an example ↓
            </Button>
          </div>
        </div>
        <div className="hero__stage" aria-hidden="true" />
      </div>
      {/* Tower lives in its own layer so it can extend below the hero and rise
          out from behind the Numbers band. */}
      <div className="hero__art">
        <Artifact kind="tower" />
      </div>
    </section>
  );
}
