# S5 — txt2kg bylaw knowledge graph → optimizer action masks [STRETCH]

| | |
|---|---|
| **Priority** | Stretch |
| **Depends on** | P09 (RAG/constraints), P10 (action masks) |
| **Status** | optional |

## Goal
Use **txt2kg** to extract bylaw entities/relations from Toronto Municipal Code text into a **machine-readable
constraint table / knowledge graph**, and turn those triples into **action masks** for the optimizer (P10) / RL
(S4) and grounded citations for the copilot (P09). Turns prose bylaws into enforced rules.

**Why:** Creativity bounty hook (the spec's named creative use) + Insight quality (constraint-aware proposals).

## Current state
- P09 has RAG over bylaw text + a hand-curated constraint checker. This automates extraction of the constraints.

## Target state
- A pipeline: bylaw docs → txt2kg → triples (e.g. `<residential_street, prohibits, through_truck>`, `<streetcar_corridor, requires, transit_signal_priority>`) → a constraint table consumed by P10's checker/masks and cited by P09.

## Design / implementation plan
1. **Extraction** (`bylaws/txt2kg.py`) — run txt2kg over the curated Municipal Code excerpts → entity/relation triples; normalize to a constraint schema.
2. **Constraint table** (`bylaws/constraints_kg.py`) — map triples → checker rules (road-class predicates, corridor predicates, dimensional minimums) consumed by P10 `optimizer/constraints.py`.
3. **Citations** — link each enforced rule back to its source bylaw section for the copilot (P09).
4. **Human review gate** — extracted rules reviewed before enforcement (don't enforce hallucinated constraints).

## Files to create / modify
**Create:** `src/torontosim/bylaws/{txt2kg,constraints_kg}.py`; `data/bylaws/kg/`; `tests/test_bylaws_kg.py`. **Modify:** P10 `optimizer/constraints.py` (load KG rules), P09 `copilot/rag.py` (cite KG provenance).

## Test-driven design
- `test_bylaws_kg.py`: a sample bylaw paragraph → expected triples; a triple → a checker rule that blocks the matching illegal action; provenance preserved.

## Verification
**Local/Spark:** extracted rules block the right actions in the optimizer; copilot cites the source section.

## Risks / fallbacks
- **txt2kg extraction noisy/hallucinated** → human-review gate before enforcement; fall back to the **hand-curated constraint set** (P09/P10) which already works. KG is an enhancement, not a dependency.
- **Tooling friction** → present a small curated KG even if full automation slips.
