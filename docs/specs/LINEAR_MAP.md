# TorontoSim — Linear backlog map

Generated from the committed specs (`docs/specs/ROADMAP.md` + `00..12` + `stretch/S1..S6`).
The build agent uses these identifiers to name branches/PRs.

- **Workspace / team:** FlowTo (issue key **`FLO`**) — the task example used `TOR-`; this workspace's team key is `FLO`.
- **Project:** TorontoSim → https://linear.app/flowtoronto/project/torontosim-e1022d5c13cf
- **Status:** all issues `Backlog`, unassigned. Core = priority High, stretch = priority Low.
- **Labels:** every phase issue carries `phase` + (`core`|`stretch`) + one area label (`data`/`sim`/`frontend`/`ai`/`infra`).
- **Estimates:** phase issues = Σ of task-day estimates rounded to the team's point scale; sub-issues = per-task day estimate rounded up to integer points (exact days are in each sub-issue description). Stretch S1–S6 have no task checklist, so they are phase-only with no estimate.

## Phase → Linear issue

| Phase | Title | Linear | Pri | Area | Est (pts / Σdays) | Blocked-by |
|---|---|---|---|---|---|---|
| P00 | Repo restructure, environment & Spark test harness | **FLO-6** | High | infra | 4 / 3.5 | — |
| P01 | Data pipeline | **FLO-7** | High | data | 5 / 4.5 | FLO-6 |
| P02 | Road graph | **FLO-8** | High | data | 4 / 4.0 | FLO-6, FLO-7 |
| P03 | Demand & OD | **FLO-9** | High | ai | 6 / 5.5 | FLO-7, FLO-8 |
| P04 | Simulation engine | **FLO-10** | High | sim | 7 / 7.0 | FLO-8, FLO-9 |
| P05 | Blast-radius | **FLO-14** | High | sim | 5 / 5.0 | FLO-10 |
| P06 | Backend API | **FLO-11** | High | infra | 4 / 4.0 | FLO-10, FLO-14 |
| P07 | Frontend | **FLO-12** | High | frontend | 7 / 6.5 | FLO-11 |
| P08 | Transit overlay | **FLO-15** | High | frontend | 4 / 3.5 | FLO-7, FLO-12 |
| P09 | Copilot | **FLO-16** | High | ai | 4 / 4.0 | FLO-11 |
| P10 | Optimizer | **FLO-17** | High | ai | 5 / 4.5 | FLO-10, FLO-11 |
| P11 | Profiling & performance | **FLO-18** | High | infra | 3 / 2.5 | FLO-10, FLO-14 |
| P12 | FIFA WC demo | **FLO-13** | High | infra | 3 / 3.25 | all core: FLO-6,7,8,9,10,11,12,14,15,16,17,18 |
| S1 | Multimodal mode-choice | **FLO-19** | Low | sim | — | FLO-9, FLO-10, FLO-15 |
| S2 | Pedestrian + bike layers | **FLO-20** | Low | frontend | — | FLO-8, FLO-12 |
| S3 | GNN / surrogate emulator | **FLO-21** | Low | ai | — | FLO-10 |
| S4 | RL proposal layer | **FLO-22** | Low | ai | — | FLO-10, FLO-14, FLO-17 |
| S5 | txt2kg bylaw knowledge graph | **FLO-23** | Low | ai | — | FLO-16, FLO-17 |
| S6 | VSS traffic-camera layer | **FLO-24** | Low | frontend | — | FLO-7, FLO-12 |

Critical path (project order): P00 → P01 → P02 → P03 → P04 → P06 → P07 → P12, then P05, P08, P09, P10, P11, then S1–S6.

## Sub-issues (T0x.y) per phase

Each core phase issue has one sub-issue per task. Identifier ranges:

| Phase | Sub-issues (T0x.y) |
|---|---|
| P00 (FLO-6) | FLO-25 … FLO-31 (T00.1–T00.7) |
| P01 (FLO-7) | FLO-32 … FLO-38 (T01.1–T01.7) |
| P02 (FLO-8) | FLO-39 … FLO-44 (T02.1–T02.6) |
| P03 (FLO-9) | FLO-45 … FLO-51 (T03.1–T03.7) |
| P04 (FLO-10) | FLO-52 … FLO-59 (T04.1–T04.8) |
| P05 (FLO-14) | FLO-60 … FLO-64 (T05.1–T05.5) |
| P06 (FLO-11) | FLO-65 … FLO-70 (T06.1–T06.6) |
| P07 (FLO-12) | FLO-71 … FLO-77 (T07.1–T07.7) |
| P08 (FLO-15) | FLO-78 … FLO-82 (T08.1–T08.5) |
| P09 (FLO-16) | FLO-83 … FLO-88 (T09.1–T09.6) |
| P10 (FLO-17) | FLO-89 … FLO-94 (T10.1–T10.6) |
| P11 (FLO-18) | FLO-95 … FLO-99 (T11.1–T11.5) |
| P12 (FLO-13) | FLO-100 … FLO-105 (T12.1–T12.6) |

Total: 19 phase issues + 81 sub-issues = 100 issues.
