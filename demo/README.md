# Demo Mode

Run the AI Grid Dashboard with synthetic data — no clusters, kubeconfigs, or external dependencies required.

## Quick Start

### Container

```bash
podman run -d -p 8501:8501 \
  -e GRID_DEMO_MODE=true \
  quay.io/karmab/ai-grid-demo:latest
```

Open http://127.0.0.1:8501.

### Local

```bash
pip install -r requirements.txt
GRID_DEMO_MODE=true uvicorn app:app --host 0.0.0.0 --port 8501
```

## What You Get

Demo mode provides a fully interactive dashboard with three synthetic clusters, pre-deployed models, live traffic animation, and fleet metrics — all generated without any real infrastructure.

| Feature | Demo behavior |
|---------|--------------|
| Cluster map | 3 clusters (vai/Azure, satch/AWS, bumblefoot/libvirt) with health indicators |
| Cluster status | Green/yellow health, node topology, GPU counts, RHOAI components |
| Model deployment | Deploy from the sidebar catalog; models persist in memory |
| Model lifecycle | Move models between clusters via drag-and-drop, delete |
| App deployment | Deploy apps with auto-generated route URLs |
| Model spreads | Pre-configured cross-cluster spreads with animated traffic lines |
| Traffic monitoring | Per-spoke request rates, latency, tokens/sec on the spread dashboard |
| Fleet metrics | Aggregate GPU utilization, tokens/sec, active model/cluster counts |
| Timeseries charts | Synthetic GPU, throughput, and queue depth curves (1h/6h/24h) |
| Cluster management | Add/remove/tag clusters without kubeconfig validation |

## Demo Guide

When demo mode is active, a **?** button appears in the top-right corner alongside a compact nav bar (`‹ [stage] ›`). Together they provide a 14-stage guided walkthrough that tells a complete story arc:

| Act | Stages | What happens |
|-----|--------|--------------|
| Setup | 1–4 | Healthy idle fleet, explore a cluster, deploy a model, register a spread |
| Growth | 5–6 | Traffic begins (light), ramps to full production |
| Crisis | 7–9 | Cluster under pressure → overloaded → traffic re-routes |
| Resolution | 10–11 | Recovery and steady state |
| Explore | 12–14 | Add a cluster, move a model, deploy an app |

**Controls:**
- **Nav bar** — click `‹` / `›` to step through stages
- **Keyboard** — left/right arrow keys
- **? panel** — click any stage to jump directly; shows description for the current stage

Each walkthrough stage sets cluster health, GPU utilization, and traffic multipliers via the scenario API so the map, metrics strip, and traffic lines all update to match the narrative.

## Scenario API

Override cluster state and traffic for custom demo scenarios:

```bash
# Set overrides
curl -X POST http://127.0.0.1:8501/api/demo/scenario \
  -H 'Content-Type: application/json' \
  -d '{
    "cluster_overrides": {
      "satch": {"health": "red", "gpu_avg": 98.0, "latency_ms": 1800}
    },
    "traffic_multipliers": {
      "satch": 0.05, "bumblefoot": 2.5
    }
  }'

# Clear overrides (revert to defaults)
curl -X DELETE http://127.0.0.1:8501/api/demo/scenario
```

**`cluster_overrides`** — per-cluster fields: `health` (green/yellow/red), `health_details`, `gpu_avg`, `latency_ms`, `reachable`.

**`traffic_multipliers`** — per-spoke scaling factor: `0` = no traffic, `1.0` = normal, `2.5` = absorbing rerouted load.

## Seed Data

Seed files in `demo/seed/` define the initial state:

- `clusters.json` — 3 clusters with coordinates, tags (vai is tagged `hub`)
- `spreads.json` — 2 model spreads referencing the seeded clusters
- `models.json` — Pre-deployed models per cluster (mix of Ready and Progressing)
- `apps.json` — One pre-deployed app with a route URL

Modify these files to change what appears on first load.

## Reset

To restore the dashboard to its initial seed state (undoing any deploys, moves, or cluster additions):

```bash
curl -X POST http://127.0.0.1:8501/api/demo/reset
```

## Running Tests

```bash
pip install pytest httpx
pytest demo/tests/ -v
```

Tests cover all 8 user stories and run entirely against the demo API — no external dependencies.

## How It Works

When `GRID_DEMO_MODE=true` is set, `app.py` installs demo route handlers (from `demo/mock_api.py`) that take priority over the real k8s-backed endpoints. The original routes remain registered but are never matched for overridden paths.

- `demo/generators.py` — Pure functions producing synthetic cluster status, metrics, traffic rates, and timeseries data
- `demo/mock_api.py` — In-memory model/app stores and route handlers
- `demo/seed/` — JSON fixtures for initial state

When `GRID_DEMO_MODE` is not set, the app behaves exactly as it does upstream — no demo code is loaded.
