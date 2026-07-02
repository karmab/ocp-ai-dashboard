# Data Sources

How the grid UI retrieves and displays cluster, model, and metrics data.

## Kubernetes API

All cluster interactions go through the Python `kubernetes` client, configured per-cluster from kubeconfig files referenced in `clusters.json`.

| Data | K8s API | Resource |
|------|---------|----------|
| Node list, roles, CPU, memory, GPU count | `CoreV1Api.list_node()` | `v1/Node` — reads `.status.allocatable["nvidia.com/gpu"]` for GPU count |
| OCP version | `CustomObjectsApi` | `config.openshift.io/v1/ClusterVersion` |
| Platform (AWS/Azure/GCP/libvirt) | `CustomObjectsApi` | `config.openshift.io/v1/Infrastructure` |
| Apps domain | `CustomObjectsApi` | `config.openshift.io/v1/Ingress` — `.spec.domain` |
| RHOAI components | `CustomObjectsApi` | `operators.coreos.com/v1alpha1/ClusterServiceVersion` |
| Deployed models | `CustomObjectsApi` | `serving.kserve.io/v1alpha2/LLMInferenceService` |
| Deployed apps | `AppsV1Api.list_deployment_for_all_namespaces()` | Deployments with label `grid.rhoai/managed=true` |
| App routes | `CustomObjectsApi` | `route.openshift.io/v1/Route` with label `grid.rhoai/managed=true` |
| MaaS subscriptions | `CustomObjectsApi` | `maas.opendatahub.io/v1alpha1/MaaSSubscription` |

## Thanos / Prometheus

Metrics are queried from each cluster's Thanos endpoint at `thanos-querier-openshift-monitoring.{apps_domain}`. Authentication uses a short-lived ServiceAccount token created for `prometheus-k8s` in `openshift-monitoring`.

### Instant queries (used for cluster health + metrics summary strip)

| Metric | PromQL | What it shows |
|--------|--------|---------------|
| GPU utilization | `DCGM_FI_DEV_GPU_UTIL` | Per-GPU utilization from NVIDIA DCGM exporter |
| Node health | `kube_node_status_condition{condition="Ready",status="true"} == 0` | Nodes not in Ready state |
| Tokens/sec | `sum(rate(vllm:generation_tokens_total[5m]))` | Aggregate token generation rate from vLLM |

### Range queries (used for time-series chart)

| Metric | PromQL | Step sizes |
|--------|--------|------------|
| GPU utilization | `avg(DCGM_FI_DEV_GPU_UTIL)` | 1h→60s, 6h→300s, 24h→900s |
| Tokens/sec | `sum(rate(vllm:generation_tokens_total[5m]))` | same |
| Queue depth | `sum(vllm:num_requests_waiting)` | same |

Queries are run in parallel across all clusters using `ThreadPoolExecutor`, then aggregated: GPU utilization is averaged, throughput and queue depth are summed.

## What maps to what in the UI

| UI element | API endpoint | Data source |
|------------|-------------|-------------|
| Cluster markers (color) | `GET /api/clusters` | Thanos (node health + GPU util) |
| Cluster info panel — topology | `GET /api/clusters/{name}/details` | K8s Node API |
| Cluster info panel — models | `GET /api/clusters/{name}/models` | KServe LLMInferenceService CRs |
| Cluster info panel — apps | `GET /api/clusters/{name}/apps` | K8s Deployments + Routes |
| Bottom strip — Total GPUs | `GET /api/metrics/summary` | Node `.status.allocatable` |
| Bottom strip — GPU Utilization | `GET /api/metrics/summary` | Thanos `DCGM_FI_DEV_GPU_UTIL` |
| Bottom strip — Tokens/sec | `GET /api/metrics/summary` | Thanos `vllm:generation_tokens_total` |
| Bottom strip — Active Models | `GET /api/metrics/summary` | KServe LLMInferenceService count |
| Bottom strip — Active Clusters | `GET /api/metrics/summary` | Clusters with GPUs or models |
| Time-series chart | `GET /api/metrics/timeseries` | Thanos range queries |
| Map link lines | `GET /api/links` | `links.json` (local file) |

## Metrics availability

- **DCGM metrics** require the NVIDIA GPU Operator with DCGM exporter. Clusters without GPUs return no data — the UI shows "N/A".
- **vLLM metrics** (`vllm:generation_tokens_total`, `vllm:num_requests_waiting`) are only available on clusters running vLLM-based inference. The UI handles their absence gracefully.
- **Cluster health** defaults to "green" when Thanos is unreachable or metrics are unavailable.
- The bottom strip auto-refreshes every 30 seconds.
