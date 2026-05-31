import { Button } from "../ui/Button";
import { Reveal } from "../ui/Reveal";
import { APP_URL } from "../constants";

export function CTA() {
  return (
    <section className="section cta">
      <div
        className="glow"
        style={{ width: 640, height: 360, left: "50%", top: "20%", transform: "translateX(-50%)" }}
      />
      <div className="container">
        <Reveal>
          <div className="cta__inner">
            <h2 className="h2-jumbo">
              Plan the city. <span className="flow-text">Before it happens.</span>
            </h2>
            <p className="body-l" style={{ maxWidth: "44ch" }}>
              Open the simulation and see how your next decision plays out —
              before you make it.
            </p>
            <Button href={APP_URL} variant="primary">
              Open the simulation →
            </Button>
          </div>
        </Reveal>
      </div>
    </section>
  );
}
