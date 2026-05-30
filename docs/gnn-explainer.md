# GNNs, from scratch — for flowTO

> A beginner's guide to Graph Neural Networks, explained with **our own Toronto
> road network** as the running example. No prior ML-on-graphs needed. Read top
> to bottom; each section builds on the last.

---

## 0. The 30-second version

A **Graph Neural Network (GNN)** is a model that learns from data shaped like a
*network* — dots connected by lines — instead of data shaped like a spreadsheet.

Our road map **is** a network: intersections are dots, road segments are lines.
A GNN can look at that map and learn things like *"how congested will this road
segment get?"* by letting each road **listen to its neighbours**, the same way
a traffic jam physically spreads from one block to the next.

That "listen to your neighbours, then update yourself, repeat" loop is the
**entire idea**. Everything below is just detail on top of it.

---

## 1. First, what's a "graph"?

Forget charts/diagrams — in this field a **graph** is just **things + the
connections between them**.

```
        Things  = NODES   (circles)
   Connections  = EDGES   (lines)
```

Our network downtown, drawn tiny:

```
        (A)───────(B)
         │         │
         │         │
        (C)───────(D)───────(E)
                   │
                   │
                  (F)
```

- **Nodes** `A…F` = intersections.
- **Edges** = road segments between them (`A–B`, `C–D`, `D–E`, …).

> In flowTO this is literally `data/graph/toronto_drive_graph.json`:
> **6,834 nodes** (intersections) and **18,190 edges** (road segments) for the
> ~7 km downtown area. Same idea, just bigger.

Every node and every edge can carry **features** — numbers describing it. We
already compute these (`src/torontosim/model/features.py`):

```
NODE features (per intersection):        EDGE features (per road segment):
  • lat / lon                              • capacity (how many cars it holds)
  • road_degree (# roads meeting here)     • base travel time
  • distance_to_downtown                   • road class (highway? arterial?)
  • near_highway?                          • current load / pressure
```

---

## 2. Why a spreadsheet model misses something

Today our demand model (`HistGradientBoostingRegressor`) is a **table** model.
It sees each intersection as **one independent row**:

```
   intersection │ hour │ road_class │ near_hwy │ → predicted cars
  ──────────────┼──────┼────────────┼──────────┼──────────────────
        A       │  8   │  arterial  │   yes    │     1200
        B       │  8   │  arterial  │   no     │      900
        C       │  8   │  local     │   no     │      300
```

The problem: **row A has no idea row B exists.** But in reality, if `B` is
gridlocked, traffic backs up *into* `A`. A table model is structurally blind to
"who is next to whom." It can only learn *"arterials at 8am are busy"* in
general — never *"this arterial is busy **because its neighbour is jammed**."*

A GNN's whole reason to exist is to fix exactly that blind spot.

---

## 3. The core mechanic: "message passing"

This is the one concept to actually understand. A GNN works in **rounds**. In
each round, every node does three steps:

```
   ┌─ 1. GATHER ──┐   ┌─ 2. AGGREGATE ─┐   ┌─ 3. UPDATE ──┐
   │ collect info │   │  combine them  │   │ revise my own │
   │ from each    │ → │  into one      │ → │ features using│
   │ neighbour    │   │  summary       │   │ that summary  │
   └──────────────┘   └────────────────┘   └───────────────┘
```

Watch node `D` (which touches `C`, `E`, `F`) do **one round**:

```
   BEFORE round 1:                     Each neighbour sends its
   every node holds its own features   current features as a "message"

        (C)──┐                              (C)──┐  msg: "load=0.9!"
             │                                    │
        (E)──┼──(D)                          (E)──┼──(D)  ← D gathers all 3
             │                                    │       messages, averages
        (F)──┘                              (F)──┘  msg: "load=0.2"

   AFTER round 1:
   D's features are updated to reflect its neighbourhood.
   D now "knows" it sits next to a congested road (C).
```

After **round 1**, every node knows about its **direct** neighbours.
After **round 2**, messages from *those* neighbours' neighbours arrive — so each
node now senses **2 hops** away. After `k` rounds, **`k` hops**.

```
   How far information travels with each round, starting from D:

   round 1:   D ← {C, E, F}                 (1 hop)
   round 2:   D ← {C,E,F} ← {A, B, …}       (2 hops)
   round 3:   …reaches the whole neighbourhood

           (A)─(B)            (A)─(B)            (A)═(B)
            │   │              │   │              ║   ║
           (C)─(D)─(E)   →    (C)═(D)═(E)   →    (C)═(D)═(E)
                │                  ║                  ║
               (F)                (F)                (F)
          ═ = "D can feel this node's influence"
```

This is **exactly how a real traffic jam spreads** — block by block, outward.
The GNN's rounds mirror the physics. That's why GNNs are a natural fit for
traffic, and a plain table model is not.

> Jargon you'll now recognise: a "round" is a **layer** or a **message-passing
> step**. "How many hops it can see" = number of layers. "Combine the messages"
> = the **aggregation** (mean / sum / max). That's 90% of GNN vocabulary.

---

## 4. How does it *learn*? (training, briefly)

Same loop as any ML model, just on graphs:

```
   1. FORWARD:  feed the graph in → GNN predicts a number per edge
                (e.g. "pressure on D–E = 0.7")

   2. COMPARE:  look at the TRUE answer (from the simulator, or real TMC counts)
                true pressure was 0.9  →  error = 0.2

   3. ADJUST:   nudge the GNN's internal knobs ("weights") so next time
                it would have said something closer to 0.9

   4. REPEAT thousands of times over many graphs/scenarios until error is small.
```

The "true answer" it learns from is called the **label** or **ground truth**.
**Where those labels come from is the big decision for flowTO** (next section).

---

## 5. The two ways we could use a GNN in flowTO

This is the fork we paused on. Both are GNNs; they differ in **what they
predict** and **what data trains them**.

### Option A — GNN as a *simulator surrogate* (the S3 spec)

```
   INPUT  (road graph + demand + an intervention, e.g. "close edge D–E")
                              │
                              ▼
                   ┌────────────────────┐
                   │   GNN (surrogate)   │   ← learns to imitate the simulator
                   └────────────────────┘
                              │
                              ▼
   OUTPUT (predicted pressure on every edge, in ~milliseconds)
```

- **Learns from:** pairs the **simulator** generates. We run the real
  propagation engine on thousands of random closures and save
  `(graph + closure) → resulting pressures`. The GNN learns to mimic it.
- **Why bother, if we already have the simulator?** Speed. The simulator takes
  a moment per scenario; the optimizer (`P10`) wants to test **millions** of
  candidate plans. The GNN gives a fast *first guess* to rank them, then the
  **real simulator double-checks only the top few**. Sim stays the source of
  truth — the GNN is just a fast pre-filter.
- **"Before/after in TMC" role:** real before/after counts let us check the
  surrogate (and the simulator itself) against reality, not just against itself.

### Option B — GNN as a *demand-model upgrade*

```
   INPUT  (road graph + time + weather)
                              │
                              ▼
                   ┌────────────────────┐
                   │   GNN (demand)      │   ← replaces the table model
                   └────────────────────┘
                              │
                              ▼
   OUTPUT (predicted baseline cars near every intersection)
```

- **Learns from:** real **TMC counts** (how many cars were actually observed).
- **What it adds over today's table model:** it can use *spatial correlation* —
  "this intersection is busy partly because its neighbours are" (the §2 blind
  spot). Still predicts **baseline** demand only; the engine still handles
  closures.

### Side by side

```
                    │ Option A: Surrogate     │ Option B: Demand GNN
   ─────────────────┼─────────────────────────┼──────────────────────────
   Predicts         │ pressure AFTER an        │ baseline cars, no
                    │ intervention             │ intervention
   Trained on       │ simulator output         │ real TMC counts
   Needs real data? │ no (sim makes its own)   │ YES (needs TMC on disk)
   Main payoff      │ optimizer goes fast      │ more accurate baseline
   "before/after"   │ validates it             │ not directly used
   Can build today? │ yes (sim works now)      │ blocked on TMC fetch
```

> Note the practical kicker: **Option A can start today** because the simulator
> generates its own training data. **Option B is blocked** until we fetch real
> TMC counts (none on disk yet — only the bylaw PDFs).

---

## 6. The "start simple" rule (don't skip this)

The S3 spec is insistent on one thing, and it's good advice:

```
   START HERE                                    ESCALATE ONLY IF IT HELPS
   ┌───────────────────────┐                     ┌───────────────────────┐
   │  XGBoost / boosted     │   if it beats the   │  true GNN              │
   │  trees on edge features│ ──baseline, stop.── │  (message passing)     │
   │  ("residual" learner)  │   if not, climb →   │                        │
   └───────────────────────┘                     └───────────────────────┘
```

Reasons to crawl before you run:
- Boosted trees train in **seconds on CPU**, need no GPU, rarely break.
- They give you a **baseline error number** to beat. A GNN that can't beat
  trees isn't worth shipping (the spec calls this the **"activation gate"** —
  only ship the GNN if it actually wins on held-out data).
- The whole pipeline (data → train → score → verify) is identical either way,
  so building it with trees first means the GNN is a **drop-in swap** later.

---

## 7. Where this physically lives in the repo

```
   src/torontosim/
     model/          ← TODAY's demand model (table). Option B would upgrade this.
       features.py        node/edge feature engineering (the GNN's inputs)
       train_demand_model.py
       ingest_real_data.py   real TMC → training rows  (feeds Option B)
       validate_past.py      before/after comparison core
       odme.py               calibrate OD to real counts
     simulation/     ← the propagation engine = the "physics" / ground truth
     surrogate/      ← DOES NOT EXIST YET. Option A (S3) would create it:
       dataset.py         run sim on random closures → (input → pressure) pairs
       gnn.py             the model (trees first, GNN later)
       infer.py           fast scoring used by the optimizer
     optimizer/      ← P10. The customer of the surrogate (ranks plans).
```

Spec: `docs/specs/stretch/S3-gnn-surrogate.md`.

---

## 8. Glossary (one line each)

| Term | Plain meaning |
|---|---|
| **Node** | A thing. For us: an intersection. |
| **Edge** | A connection. For us: a road segment. |
| **Feature** | A number describing a node/edge (e.g. capacity, hour). |
| **Message passing** | Nodes share features with neighbours each round. |
| **Layer / round / hop** | One message-passing step; `k` layers = sees `k` hops out. |
| **Aggregation** | How a node combines its neighbours' messages (mean/sum/max). |
| **Label / ground truth** | The true answer we train against (sim output or real count). |
| **Surrogate** | A fast model that imitates a slow exact one (the simulator). |
| **Residual learner** | Predict only the *correction* on top of a simple baseline. |
| **Activation gate** | Only ship the fancy model if it beats the simple one. |

---

## 9. TL;DR

1. Our road map is a **graph** (intersections = nodes, roads = edges).
2. A **GNN** lets each road **learn from its neighbours** over several rounds —
   mirroring how congestion actually spreads. A table model can't do this.
3. We can point it two ways: **(A)** a fast *stand-in for the simulator* to speed
   up the optimizer, or **(B)** a smarter *demand model* using real counts.
4. **Build with boosted trees first**, prove it beats the baseline, then swap in
   a real GNN only if it wins.
5. Option A can start **today**; Option B waits on fetching real **TMC** data.
