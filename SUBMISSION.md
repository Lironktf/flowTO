# Submission checklist — FlowTO

> Spark Hack Series · **Due: May 31, 11:00 am** · one submission per team.
> This file mirrors the official checklist and points to where each item lives.

## Required

- [x] **Team name** — FlowTO
- [x] **Project description** — [`README.md`](README.md#flowto--a-live-digital-twin-of-toronto)
- [x] **Challenge selected** — Environmental Impact (urban mobility) — [README › Challenge & bounties](README.md#challenge--bounties)
- [ ] **3–5 min demo video** (unlisted YouTube/Vimeo, core loop live) — **add link** in [README › Demo video](README.md#demo-video); run-of-show in [`demo/RUNBOOK.md`](demo/RUNBOOK.md)
- [x] **Repo link** (public or invite judges) — https://github.com/Lironktf/flowTO
  - [x] **Quick start** (commands to run) — [README › Quick start](README.md#quick-start)
  - [x] **Tech stack & architecture diagram** — [README › Architecture](README.md#architecture)
  - [x] **How to reproduce the demo** (env vars, API keys, sample `.env`) — [README › Reproduce the demo](README.md#reproduce-the-demo) + [`frontend/.env.example`](frontend/.env.example)
  - [x] **Datasets / synthetic data + provenance** — [README › Datasets & provenance](README.md#datasets--provenance)
  - [x] **Known limitations & next steps** — [README › Known limitations & next steps](README.md#known-limitations--next-steps)
- [x] **Deployed URL (if any)** — on-device only; no public URL. Screen capture / demo video stands in.
- [x] **Team roster** (names, roles, contacts) — [README › Team roster](README.md#team-roster)

## Action items before submitting

1. **Record + link the 3–5 min demo video** (unlisted) and paste the URL into the README "Demo video" section and the checklist above.
2. **Confirm the team roster** — fill in each member's **role** and any missing **contact** (drafted from git history; marked `_TBD_`).
3. **Verify judge access** to https://github.com/Lironktf/flowTO (public, or invite the judges).
4. *(Optional)* Rotate the local Mapbox token if it was ever shared; `frontend/.env` is untracked, so nothing is committed.

## One-paragraph project description (for the submission form)

> **FlowTO** is a live, 100%-on-device digital twin of Toronto's road and transit
> network, built and run on an NVIDIA DGX Spark (GB10). Planners scrub a real
> matchday timeline, inject a FIFA WC 2026 post-match surge at BMO Field, and ask
> an on-device Nemotron copilot to ease the resulting gridlock — it returns a
> bylaw-checked, cited plan that the engine recomputes in milliseconds via an
> adaptive blast-radius solver, melting congestion red → green with a headline
> Before/After metric. The assignment engine (BPR + Frank-Wolfe user equilibrium)
> is validated against the published SiouxFalls benchmark to ~0.1%, the optimizer
> scores every plan by actually running the simulation (sim-as-verifier), and the
> whole stack — sim, LLM, and data pipeline — runs locally on Arm with no cloud.
