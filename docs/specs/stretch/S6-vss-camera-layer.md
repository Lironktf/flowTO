# S6 — VSS traffic-camera validation layer [STRETCH]

| | |
|---|---|
| **Priority** | Stretch (lowest) |
| **Depends on** | P01 (camera data), P07 (frontend) |
| **Status** | optional |

## Goal
Add an optional layer of **traffic-camera locations** (City "Traffic Camera List") as map markers, with an optional
**NVIDIA VSS** (Video Search & Summarization) hook to connect a camera to visual verification of a corridor's state
— "is this segment actually congested?" Pure validation/polish; not on the demo critical path.

**Why:** Optional credibility + an extra NVIDIA-stack name-drop. Lowest-priority stretch.

## Current state
- None. P01 can bake the Traffic Camera List GeoJSON (research/01 noted it as optional).

## Target state
- Camera markers on the map; clicking a camera shows its location + (stretch) a VSS-generated summary of the live/recent view; used to spot-check the sim against reality.

## Design / implementation plan
1. **Camera data** (P01) — bake "Traffic Camera List - 4326.geojson" → camera positions.
2. **Frontend** (P07) — `IconLayer` of cameras; click → side panel with location + optional image/summary.
3. **VSS hook (optional)** (`vss/summarize.py`) — connect a camera feed/snapshot to NVIDIA VSS for a text summary ("moderate congestion, queue on the eastbound approach"); compare to sim pressure for that edge.

## Files to create / modify
**Create:** `src/torontosim/vss/summarize.py`; `frontend/src/layers/cameras.ts`; `tests/test_cameras.py`. **Modify:** P01 (bake camera list), P07 (camera layer + panel).

## Test-driven design
- Camera GeoJSON loads → markers; click selects a camera; (if VSS) a summary string returns for a sample frame.

## Verification
**Local:** camera markers render + select. **On Spark:** VSS summarizes a sample frame on-device (if attempted).

## Risks / fallbacks
- **VSS heavy / not needed** → ship camera markers only; VSS is explicitly optional (spec marks VSS "optional").
- **No live feeds** → static camera locations + a recent snapshot suffice for the validation story.
