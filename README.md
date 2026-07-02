# AI Grid Demo

Map-based dashboard for managing RHOAI MaaS clusters, models, and cross-cluster load balancing via LiteLLM.

## Image

```
quay.io/karmab/ai-grid-demo:latest
```

## Running

```bash
podman run -d -p 8501:8501 \
  -v /path/to/data:/data:Z \
  quay.io/karmab/ai-grid-demo:latest
```

Then open http://localhost:8501.

## Data directory

The container expects a `/data` volume with the following structure:

```
/data/
├── clusters.json          # cluster definitions
├── links.json             # model links (created automatically if missing)
├── keys/
│   ├── vai.key            # MaaS API key for cluster "vai"
│   ├── mai.key
│   └── cluster1.key
└── kubeconfigs/
    ├── vai.kubeconfig
    ├── mai.kubeconfig
    └── cluster1.kubeconfig
```

### clusters.json

```json
[
  {
    "name": "vai",
    "display_name": "vai (Azure)",
    "kubeconfig": "/data/kubeconfigs/vai.kubeconfig",
    "lat": 37.37,
    "lon": -122.04
  },
  {
    "name": "mai",
    "display_name": "mai (AWS)",
    "kubeconfig": "/data/kubeconfigs/mai.kubeconfig",
    "lat": 45.52,
    "lon": -122.68
  }
]
```

Kubeconfig paths must be container-side paths (i.e. under `/data/kubeconfigs/`).

### API key files

The app reads MaaS API keys from `{GRID_KEYS_DIR}/{cluster_name}.key`. With the default `GRID_KEYS_DIR=/data/keys`, a cluster named `vai` needs its key at `/data/keys/vai.key`.

These keys are used for cross-cluster model linking (LiteLLM proxy deployment).

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `GRID_DATA_DIR` | `/data` | Directory for `clusters.json` and `links.json` |
| `GRID_KEYS_DIR` | `/data/keys` | Directory for `{cluster}.key` files |

## Local development

```bash
cd grid
pip install -r requirements.txt
uvicorn app:app --host 0.0.0.0 --port 8501
```

When running locally, `GRID_DATA_DIR` defaults to the `grid/` directory and `GRID_KEYS_DIR` defaults to its parent.
