import { Button } from "../ui/Button";
import { APP_URL } from "../constants";

export function Nav() {
  return (
    <header className="nav">
      <div className="container nav__inner">
        <a className="wordmark" href="/">
          flow<b>TO</b>
        </a>
        <nav className="nav__links">
          <a href="#scenario">The challenge</a>
          <a href="#modes">Two ways</a>
          <a href="#engine">Why trust it</a>
          <a href="#how">How it works</a>
        </nav>
        <Button href={APP_URL} variant="primary">
          Open the simulation
        </Button>
      </div>
    </header>
  );
}
