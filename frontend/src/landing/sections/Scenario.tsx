import { Badge } from "../ui/Badge";
import { Reveal } from "../ui/Reveal";
import { Artifact } from "../scene/Artifact";

export function Scenario() {
  return (
    <section className="section" id="scenario">
      <div className="container">
        <div
          className="grid-2"
          style={{ alignItems: "center", gap: 48 }}
        >
          <Reveal>
            <Badge>The challenge</Badge>
            <h2 className="h2" style={{ marginTop: 18 }}>
              45,000 people. One whistle. Total gridlock.
            </h2>
            <p className="body-l" style={{ marginTop: 20 }}>
              When a FIFA World Cup 2026 match lets out, tens of thousands leave
              BMO Field at once — and the whole area locks up. With flowTO you
              can see exactly where the jams will form, test a plan to clear
              them — extra streetcars, road closures, reversible lanes — and
              watch the map turn from red to green. All before the whistle ever
              blows.
            </p>
            <div style={{ marginTop: 30 }}>
              <div className="heatstrip" />
              <div className="heatstrip__labels">
                <span>Free flow</span>
                <span>Gridlock</span>
              </div>
            </div>
          </Reveal>
          <div
            className="hero__stage"
            style={{ minHeight: 420, position: "relative" }}
          >
            <Artifact kind="trophy" gate />
          </div>
        </div>
      </div>
    </section>
  );
}
