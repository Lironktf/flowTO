export function Footer() {
  return (
    <footer className="footer">
      <div className="container footer__inner">
        <div>
          <a className="wordmark" href="/">
            flow<b>TO</b>
          </a>
          <p className="footer__attr">
            Contains data licensed under the Open Government Licence – Toronto &
            Ontario; weather from Environment and Climate Change Canada.
          </p>
          <p className="footer__attr">
            3D models:{" "}
            <a
              href="https://www.printables.com/model/300561-torontos-cn-tower-multi-part-single-print"
              target="_blank"
              rel="noopener noreferrer"
            >
              “Toronto's CN Tower”
            </a>{" "}
            by Marek Holly and{" "}
            <a
              href="https://www.printables.com/model/113249-fifa-world-cup-trophy"
              target="_blank"
              rel="noopener noreferrer"
            >
              “FIFA World Cup Trophy”
            </a>{" "}
            by 3DPrintNovesia, via Printables.
          </p>
        </div>
        <div className="footer__meta" style={{ textAlign: "right" }}>
          Runs securely on-premises.
        </div>
      </div>
    </footer>
  );
}
