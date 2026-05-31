import React from "react";
import ReactDOM from "react-dom/client";
import { LandingApp } from "./LandingApp";
import "./styles/landing.css";
import "./styles/hero.css";
import "./styles/scenario.css";
import "./styles/twomodes.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <LandingApp />
  </React.StrictMode>,
);
