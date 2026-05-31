# FlowTO GNN Baseline Congestion Model

This replaces the old baseline-ML framing with a Graph Neural Network as the
main model. The GNN learns normal road-edge congestion from the Toronto road
network structure. The router and propagation engine still handle counterfactual
edits after the baseline is initialized.

## Why A GNN

Road segments are not independent rows. Congestion on King, Bathurst, Spadina,
the Gardiner, or DVP depends on nearby links, intersection connectivity, road
class, capacity, and time context. A GraphSAGE edge predictor lets each edge use
embeddings from its source and destination nodes, so predictions include local
network structure instead of only per-road tabular fields.

## What It Predicts

The first target is `predicted_pressure`, where:

```text
pressure = observed_vehicle_count / edge_capacity
```

Inference exports every edge with:

- `predicted_pressure`
- `predicted_load`
- `capacity`
- `base_time_min`
- `predicted_time_min`
- `risk` bucket: `low`, `moderate`, `high`, or `severe`

The model is a baseline model only. It is not responsible for predicting every
possible closure or road edit.

## Features

Node features:

- latitude, longitude
- total degree, in-degree, out-degree
- distance to downtown
- optional PageRank

Edge features:

- length, road class rank, road class one-hot
- lanes, speed, capacity, base travel time
- one-way flag
- bearing
- endpoint node degrees

Context features:

- hour, day of week, month
- weekend and rush-hour flags
- weather clear/rain/snow flags
- temperature and precipitation
- season one-hot

Weather defaults to clear when unavailable, but the feature interface is kept.

## Labels

The builder supports direct edge labels when a CSV contains `edge_id` plus
`observed_vehicle_count` or `vehicle_count`.

The current repo also has Toronto intersection count rows under
`data/model/training_dataset.csv` and `data/model/validation_dataset.csv`.
Those are projected to incident road segments as fallback labels so the GNN can
train before midblock labels are wired.

Targets are clipped to a default max pressure of `2.0` for training stability.

## Simulator Initialization

Use:

```python
from models.gnn.gnn_to_sim_adapter import apply_gnn_baseline_to_graph

apply_gnn_baseline_to_graph(graph, time_context={
    "hour": 17,
    "day_of_week": 4,
    "month": 6,
    "weather": "clear",
})
```

This sets each edge:

- `edge["load"]`
- `edge["pressure"]`
- `edge["current_time_min"]`

The existing router then routes on current edge travel times.

## Why The Router Still Matters

The GNN gives the learned spatial baseline. It does not simulate user edits.
After the baseline is applied, the existing router/propagation engine handles:

- add/delete/close edge
- reduce capacity
- event demand
- rerouting and impact comparison

The intended split is:

```text
GNN = learned spatial traffic baseline
Router = best-path assignment
Propagation engine = scenario impact after edge edits
```

## GX10 Training

Install the GNN stack on the ASUS GX10:

```bash
python -m venv .venv-gnn
. .venv-gnn/bin/activate
pip install -U pip
pip install -r models/gnn/requirements-gx10.txt
```

For NVIDIA acceleration, install the CUDA-compatible PyTorch and PyG wheels for
the GX10 image you are using. RAPIDS `cudf`/`cugraph` are optional; the training
script records whether CUDA, PyG, cuDF, and cuGraph are available.

Build the dataset with optional RAPIDS/cuGraph PageRank when available:

```bash
python -m models.gnn.build_gnn_dataset --pagerank
```

Train GraphSAGE on CUDA if available:

```bash
python -m models.gnn.train_gnn --epochs 50 --batch-size 8192 --backend graphsage
```

Outputs:

- `models/gnn/gnn_edge_congestion.pt`
- `data/gnn/gnn_dataset.pt`
- `data/gnn/training_metrics.json`

`training_metrics.json` includes the selected device and whether CUDA was used.

One-command GX10 run:

```bash
bash models/gnn/train_on_gx10.sh 50 8192
```

That script assumes the raw Toronto TMC/weather files already exist under
`data/raw`, which is what this command fetches:

```bash
WITH_2010S=1 YEARS="2017 2018 2019 2020 2021 2022 2023 2024" bash scripts/fetch_data.sh
```

The GX10 script then runs the existing real-data ingest, converts the resulting
node/intersection count CSVs into edge-labelled GNN samples, trains GraphSAGE,
and exports baseline edge predictions.

If PyTorch Geometric is not installed, `--backend auto` can fall back to the
graph-feature MLP for smoke testing. Use `--backend graphsage` for the actual
hackathon model so missing PyG fails loudly instead of silently changing model
class.

## Inference

Export a baseline for a selected context:

```bash
python -m models.gnn.predict_gnn_baseline \
  --hour 17 \
  --day-of-week 4 \
  --month 6 \
  --weather clear
```

Output:

- `data/results/gnn_baseline_predictions.json`

The first success condition is that every Toronto road edge gets a predicted
pressure. The second is that those predictions initialize the router through
`models/gnn/gnn_to_sim_adapter.py`.
