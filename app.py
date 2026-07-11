import hashlib
import json
import os
import ssl
import time
import traceback
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from kubernetes import client, config
from kubernetes.dynamic import DynamicClient

app = FastAPI()

DATA_DIR = Path(os.environ.get("GRID_DATA_DIR", str(Path(__file__).parent)))
CLUSTERS_FILE = DATA_DIR / "clusters.json"
SPREADS_FILE = DATA_DIR / "spreads.json"
KEYS_DIR = Path(os.environ.get("GRID_KEYS_DIR", str(Path(__file__).parent.parent)))
MAAS_GROUP = "maas.opendatahub.io"
MAAS_VERSION = "v1alpha1"
KSERVE_GROUP = "serving.kserve.io"
KSERVE_VERSION = "v1alpha2"


def load_clusters():
    if not CLUSTERS_FILE.exists():
        return []
    with open(CLUSTERS_FILE) as f:
        return json.load(f)


def save_clusters(clusters):
    with open(CLUSTERS_FILE, "w") as f:
        json.dump(clusters, f, indent=2)


def get_k8s_clients(kubeconfig_path):
    api_client = config.new_client_from_config(config_file=kubeconfig_path)
    api_client.configuration.retries = 0
    return {
        "core": client.CoreV1Api(api_client),
        "custom": client.CustomObjectsApi(api_client),
        "api_client": api_client,
    }

K8S_TIMEOUT = 5

REGION_COORDS = {
    # AWS
    "us-east-1": (38.95, -77.45), "us-east-2": (39.96, -83.00),
    "us-west-1": (37.35, -121.96), "us-west-2": (45.52, -122.68),
    "ca-central-1": (45.50, -73.55), "eu-west-1": (53.35, -6.26),
    "eu-west-2": (51.51, -0.13), "eu-west-3": (48.86, 2.35),
    "eu-central-1": (50.11, 8.68), "eu-central-2": (47.37, 8.54),
    "eu-north-1": (59.33, 18.07), "eu-south-1": (45.46, 9.19),
    "ap-northeast-1": (35.68, 139.69), "ap-northeast-2": (37.57, 126.98),
    "ap-southeast-1": (1.35, 103.82), "ap-southeast-2": (-33.87, 151.21),
    "ap-south-1": (19.08, 72.88), "sa-east-1": (-23.55, -46.63),
    "me-south-1": (26.07, 50.56), "af-south-1": (-33.93, 18.42),
    # Azure
    "eastus": (37.37, -79.45), "eastus2": (36.67, -78.93),
    "westus": (37.37, -122.04), "westus2": (47.61, -122.33),
    "westus3": (33.45, -112.07), "centralus": (41.88, -93.10),
    "northcentralus": (41.88, -87.63), "southcentralus": (29.43, -98.49),
    "westcentralus": (40.89, -110.23),
    "canadacentral": (43.65, -79.38), "canadaeast": (46.81, -71.21),
    "northeurope": (53.35, -6.26), "westeurope": (52.37, 4.90),
    "uksouth": (51.51, -0.13), "ukwest": (51.48, -3.18),
    "francecentral": (48.86, 2.35), "francesouth": (43.60, 1.44),
    "germanywestcentral": (50.11, 8.68), "switzerlandnorth": (47.37, 8.54),
    "norwayeast": (59.91, 10.75), "swedencentral": (59.33, 18.07),
    "australiaeast": (-33.87, 151.21), "australiasoutheast": (-37.81, 144.96),
    "japaneast": (35.68, 139.69), "japanwest": (34.69, 135.50),
    "koreacentral": (37.57, 126.98), "southeastasia": (1.35, 103.82),
    "eastasia": (22.28, 114.16), "centralindia": (18.58, 73.92),
    "brazilsouth": (-23.55, -46.63), "southafricanorth": (-25.73, 28.22),
    # GCP
    "us-central1": (41.26, -95.86), "us-east1": (33.20, -80.02),
    "us-east4": (39.03, -77.47), "us-west1": (45.60, -121.18),
    "us-west2": (34.05, -118.24), "us-west3": (40.76, -111.89),
    "us-west4": (36.17, -115.14),
    "europe-west1": (50.44, 3.82), "europe-west2": (51.51, -0.13),
    "europe-west3": (50.11, 8.68), "europe-west4": (53.44, 6.84),
    "europe-west6": (47.37, 8.54), "europe-north1": (60.57, 27.19),
    "asia-east1": (24.05, 120.52), "asia-northeast1": (35.68, 139.69),
    "asia-southeast1": (1.35, 103.82), "australia-southeast1": (-33.87, 151.21),
    "southamerica-east1": (-23.55, -46.63),
}


GPU_YELLOW_THRESHOLD = 90

# --- Caches for spread metrics performance ---
_thanos_cache = {}   # cluster_name -> (query_instant, query_range, expires_at)
_region_cache = {}   # cluster_name -> region_string
_hub_url_cache = {}  # hub_cluster_name -> (url, expires_at)

THANOS_CACHE_TTL = 300  # token valid 600s, refresh at 300
HUB_URL_CACHE_TTL = 120


def _get_cached_thanos(cluster):
    name = cluster.get("name", cluster["kubeconfig"])
    now = time.time()
    cached = _thanos_cache.get(name)
    if cached and cached[2] > now:
        return cached[0], cached[1]
    qi, qr = get_thanos_querier(cluster)
    _thanos_cache[name] = (qi, qr, now + THANOS_CACHE_TTL)
    return qi, qr


def _get_cached_region(cluster):
    name = cluster.get("name", cluster["kubeconfig"])
    if name in _region_cache:
        return _region_cache[name]
    try:
        clients = get_k8s_clients(cluster["kubeconfig"])
        nodes = clients["core"].list_node(_request_timeout=K8S_TIMEOUT)
        for node in nodes.items:
            region = (node.metadata.labels or {}).get("topology.kubernetes.io/region", "")
            if region:
                _region_cache[name] = region
                return region
    except Exception:
        pass
    _region_cache[name] = ""
    return ""


def _get_cached_hub_url(hub_cluster):
    name = hub_cluster.get("name", hub_cluster["kubeconfig"])
    now = time.time()
    cached = _hub_url_cache.get(name)
    if cached and cached[1] > now:
        return cached[0]
    hub_url = ""
    try:
        clients = get_k8s_clients(hub_cluster["kubeconfig"])
        routes = clients["custom"].list_namespaced_custom_object(
            group="route.openshift.io", version="v1",
            namespace="aig-routing", plural="routes",
            _request_timeout=K8S_TIMEOUT,
        ).get("items", [])
        for r in routes:
            host = r.get("spec", {}).get("host", "")
            if host:
                hub_url = f"https://{host}"
                break
    except Exception:
        pass
    _hub_url_cache[name] = (hub_url, now + HUB_URL_CACHE_TTL)
    return hub_url


def get_thanos_querier(cluster):
    clients = get_k8s_clients(cluster["kubeconfig"])
    custom = clients["custom"]
    ingress = custom.get_cluster_custom_object(
        group="config.openshift.io", version="v1",
        plural="ingresses", name="cluster",
        _request_timeout=K8S_TIMEOUT,
    )
    apps_domain = ingress["spec"]["domain"]
    thanos_host = f"thanos-querier-openshift-monitoring.{apps_domain}"
    token = clients["core"].create_namespaced_service_account_token(
        name="prometheus-k8s",
        namespace="openshift-monitoring",
        body={
            "apiVersion": "authentication.k8s.io/v1",
            "kind": "TokenRequest",
            "spec": {"expirationSeconds": 600},
        },
        _request_timeout=K8S_TIMEOUT,
    ).status.token

    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    def query_instant(promql):
        url = f"https://{thanos_host}/api/v1/query?query={urllib.request.quote(promql)}"
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
        with urllib.request.urlopen(req, context=ctx, timeout=10) as resp:
            data = json.loads(resp.read())
        return data.get("data", {}).get("result", [])

    def query_range(promql, start, end, step):
        url = (f"https://{thanos_host}/api/v1/query_range"
               f"?query={urllib.request.quote(promql)}"
               f"&start={start}&end={end}&step={step}")
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
        with urllib.request.urlopen(req, context=ctx, timeout=15) as resp:
            data = json.loads(resp.read())
        return data.get("data", {}).get("result", [])

    return query_instant, query_range


def get_cluster_health(cluster):
    try:
        query_instant, _ = get_thanos_querier(cluster)

        not_ready = query_instant('kube_node_status_condition{condition="Ready",status="true"} == 0')
        node_issues = len(not_ready)

        gpu_results = query_instant("DCGM_FI_DEV_GPU_UTIL")
        gpu_utils = [float(r["value"][1]) for r in gpu_results if r["value"][1]]
        avg_gpu = sum(gpu_utils) / len(gpu_utils) if gpu_utils else 0

        if node_issues > 0:
            health = "red" if node_issues > 1 else "yellow"
            detail = f"{node_issues} node(s) not ready"
        elif avg_gpu >= GPU_YELLOW_THRESHOLD:
            health = "yellow"
            detail = f"GPU avg {avg_gpu:.0f}%"
        else:
            health = "green"
            detail = f"GPU avg {avg_gpu:.0f}%" if gpu_utils else "healthy"

        return {
            "health": health,
            "health_details": detail,
            "gpu_avg": round(avg_gpu, 1),
            "gpu_count": len(gpu_utils),
        }
    except Exception:
        return {"health": "green", "health_details": "metrics unavailable"}


def cluster_status(cluster):
    try:
        clients = get_k8s_clients(cluster["kubeconfig"])
        nodes = clients["core"].list_node(_request_timeout=K8S_TIMEOUT)
        node_list = []
        ready_count = 0
        region = None
        for node in nodes.items:
            ready = False
            for cond in node.status.conditions or []:
                if cond.type == "Ready" and cond.status == "True":
                    ready = True
                    break
            if ready:
                ready_count += 1
            labels = node.metadata.labels or {}
            roles = []
            for label in labels:
                if label.startswith("node-role.kubernetes.io/"):
                    roles.append(label.split("/")[1])
            if not region:
                region = labels.get("topology.kubernetes.io/region", "")
            node_list.append({
                "name": node.metadata.name,
                "roles": roles,
                "ready": ready,
            })
        result = {
            "reachable": True,
            "nodes": node_list,
            "node_count": len(node_list),
            "ready_nodes": ready_count,
            "region": region or "",
        }
        if region and region in REGION_COORDS:
            result["detected_lat"], result["detected_lon"] = REGION_COORDS[region]
        return result
    except Exception:
        return {"reachable": False, "nodes": [], "node_count": 0, "ready_nodes": 0, "region": ""}


def list_models(cluster):
    try:
        clients = get_k8s_clients(cluster["kubeconfig"])
        custom = clients["custom"]
        items = custom.list_cluster_custom_object(
            group=KSERVE_GROUP, version=KSERVE_VERSION, plural="llminferenceservices",
            _request_timeout=K8S_TIMEOUT,
        ).get("items", [])
        models = []
        for item in items:
            spec = item.get("spec", {})
            status = item.get("status", {})
            model_spec = spec.get("model", {})
            replicas = spec.get("replicas", 1)
            conditions = status.get("conditions", [])
            ready = any(
                c.get("type") == "Ready" and c.get("status") == "True"
                for c in conditions
            )
            gpu_count = 0
            for container in spec.get("template", {}).get("containers", []):
                limits = container.get("resources", {}).get("limits", {})
                gpu_count += int(limits.get("nvidia.com/gpu", 0))
            models.append({
                "name": item["metadata"]["name"],
                "namespace": item["metadata"]["namespace"],
                "model_id": model_spec.get("name", model_spec.get("uri", "unknown")),
                "replicas": replicas,
                "ready": ready,
                "gpu_per_replica": gpu_count,
                "status": "Ready" if ready else "Progressing",
            })
        return models
    except Exception as e:
        traceback.print_exc()
        return []


GRID_LABEL = "grid.rhoai/managed"


def list_apps(cluster):
    try:
        clients = get_k8s_clients(cluster["kubeconfig"])
        apps_api = client.AppsV1Api(clients["api_client"])
        custom = clients["custom"]
        deployments = apps_api.list_deployment_for_all_namespaces(
            label_selector=GRID_LABEL, _request_timeout=K8S_TIMEOUT,
        )

        route_map = {}
        try:
            routes = custom.list_cluster_custom_object(
                group="route.openshift.io", version="v1",
                plural="routes", label_selector=GRID_LABEL,
                _request_timeout=K8S_TIMEOUT,
            ).get("items", [])
            for r in routes:
                key = f"{r['metadata']['namespace']}/{r['metadata']['name']}"
                host = r.get("spec", {}).get("host", "")
                if host:
                    route_map[key] = f"https://{host}"
        except Exception:
            pass

        apps = []
        for d in deployments.items:
            ready = (d.status.ready_replicas or 0) == (d.spec.replicas or 1)
            image = ""
            if d.spec.template.spec.containers:
                image = d.spec.template.spec.containers[0].image
            route_key = f"{d.metadata.namespace}/{d.metadata.name}"
            apps.append({
                "name": d.metadata.name,
                "namespace": d.metadata.namespace,
                "image": image,
                "replicas": d.spec.replicas or 1,
                "ready_replicas": d.status.ready_replicas or 0,
                "ready": ready,
                "route_url": route_map.get(route_key),
            })
        return apps
    except Exception:
        traceback.print_exc()
        return []


# --- API endpoints ---

@app.get("/api/clusters")
def api_list_clusters():
    clusters = load_clusters()
    return [
        {
            "name": c["name"],
            "display_name": c["display_name"],
            "lat": c.get("lat", 0),
            "lon": c.get("lon", 0),
            "tags": c.get("tags", []),
        }
        for c in clusters
    ]


@app.get("/api/clusters/{name}/status")
def api_cluster_status(name: str):
    clusters = load_clusters()
    c = next((c for c in clusters if c["name"] == name), None)
    if not c:
        raise HTTPException(404, f"Cluster '{name}' not found")
    info = cluster_status(c)
    health = get_cluster_health(c) if info["reachable"] else {"health": "red", "health_details": "unreachable"}
    return {**info, **health}


@app.get("/api/clusters/{name}/details")
def api_cluster_details(name: str):
    clusters = load_clusters()
    cluster = next((c for c in clusters if c["name"] == name), None)
    if not cluster:
        raise HTTPException(404, f"Cluster '{name}' not found")
    try:
        clients = get_k8s_clients(cluster["kubeconfig"])
        core = clients["core"]
        custom = clients["custom"]
        api_client = clients["api_client"]

        ocp_version = "unknown"
        platform = "unknown"
        try:
            cv = custom.get_cluster_custom_object(
                group="config.openshift.io", version="v1",
                plural="clusterversions", name="version",
                _request_timeout=K8S_TIMEOUT,
            )
            history = cv.get("status", {}).get("history", [])
            if history:
                ocp_version = history[0].get("version", "unknown")
            infra = custom.get_cluster_custom_object(
                group="config.openshift.io", version="v1",
                plural="infrastructures", name="cluster",
                _request_timeout=K8S_TIMEOUT,
            )
            platform = infra.get("status", {}).get("platformStatus", {}).get("type", "unknown")
        except Exception:
            pass

        nodes_raw = core.list_node(_request_timeout=K8S_TIMEOUT)
        topology = []
        for node in nodes_raw.items:
            labels = node.metadata.labels or {}
            roles = [l.split("/")[1] for l in labels if l.startswith("node-role.kubernetes.io/")]
            ready = any(
                c.type == "Ready" and c.status == "True"
                for c in (node.status.conditions or [])
            )
            cap = node.status.capacity or {}
            alloc = node.status.allocatable or {}
            topology.append({
                "name": node.metadata.name,
                "roles": roles,
                "ready": ready,
                "cpu": alloc.get("cpu", "?"),
                "memory": alloc.get("memory", "?"),
                "gpu": alloc.get("nvidia.com/gpu", "0"),
                "instance_type": labels.get("node.kubernetes.io/instance-type",
                                            labels.get("beta.kubernetes.io/instance-type", "")),
                "zone": labels.get("topology.kubernetes.io/zone", ""),
                "arch": labels.get("kubernetes.io/arch", ""),
            })

        rhoai = {}
        try:
            csvs = custom.list_namespaced_custom_object(
                group="operators.coreos.com", version="v1alpha1",
                namespace="redhat-ods-operator", plural="clusterserviceversions",
                _request_timeout=K8S_TIMEOUT,
            ).get("items", [])
            if not csvs:
                for ns_name in ["openshift-operators", "rhods-operator"]:
                    try:
                        csvs = custom.list_namespaced_custom_object(
                            group="operators.coreos.com", version="v1alpha1",
                            namespace=ns_name, plural="clusterserviceversions",
                            _request_timeout=K8S_TIMEOUT,
                        ).get("items", [])
                        if csvs:
                            break
                    except Exception:
                        pass
            for csv in csvs:
                csv_name = csv["metadata"]["name"]
                version = csv.get("spec", {}).get("version", "")
                display = csv.get("spec", {}).get("displayName", csv_name)
                phase = csv.get("status", {}).get("phase", "unknown")
                if any(k in csv_name.lower() for k in ["rhods", "opendatahub", "serverless", "servicemesh", "authorino", "kserve"]):
                    rhoai[display] = {"version": version, "phase": phase}
        except Exception:
            pass

        return {
            "ocp_version": ocp_version,
            "platform": platform,
            "topology": topology,
            "rhoai_components": rhoai,
        }
    except Exception as e:
        raise HTTPException(500, str(e))


class ClusterCreate(BaseModel):
    name: str
    display_name: str
    kubeconfig_path: str
    lat: float
    lon: float


@app.post("/api/clusters")
def api_add_cluster(body: ClusterCreate):
    clusters = load_clusters()
    if any(c["name"] == body.name for c in clusters):
        raise HTTPException(400, f"Cluster '{body.name}' already exists")
    if not os.path.isfile(body.kubeconfig_path):
        raise HTTPException(400, f"Kubeconfig not found: {body.kubeconfig_path}")
    entry = {
        "name": body.name,
        "display_name": body.display_name,
        "kubeconfig": body.kubeconfig_path,
        "lat": body.lat,
        "lon": body.lon,
    }
    try:
        get_k8s_clients(body.kubeconfig_path)["core"].list_node()
    except Exception as e:
        raise HTTPException(400, f"Cannot connect to cluster: {e}")
    clusters.append(entry)
    save_clusters(clusters)
    return {"ok": True, "cluster": entry}


@app.delete("/api/clusters/{name}")
def api_delete_cluster(name: str):
    clusters = load_clusters()
    clusters = [c for c in clusters if c["name"] != name]
    save_clusters(clusters)
    return {"ok": True}


class TagsUpdate(BaseModel):
    tags: list[str]


@app.put("/api/clusters/{name}/tags")
def api_update_tags(name: str, body: TagsUpdate):
    clusters = load_clusters()
    cluster = next((c for c in clusters if c["name"] == name), None)
    if not cluster:
        raise HTTPException(404, f"Cluster '{name}' not found")
    cluster["tags"] = body.tags
    save_clusters(clusters)
    return {"ok": True, "tags": cluster["tags"]}


@app.get("/api/clusters/{name}/models")
def api_list_models(name: str):
    clusters = load_clusters()
    cluster = next((c for c in clusters if c["name"] == name), None)
    if not cluster:
        raise HTTPException(404, f"Cluster '{name}' not found")
    return list_models(cluster)


class ModelDeploy(BaseModel):
    model_name: str
    model_id: str
    namespace: str
    replicas: int = 1
    gpu_count: int = 1
    cpu_only: bool = False


@app.post("/api/clusters/{name}/models")
def api_deploy_model(name: str, body: ModelDeploy):
    clusters = load_clusters()
    cluster = next((c for c in clusters if c["name"] == name), None)
    if not cluster:
        raise HTTPException(404, f"Cluster '{name}' not found")
    try:
        clients = get_k8s_clients(cluster["kubeconfig"])
        core = clients["core"]
        custom = clients["custom"]

        try:
            core.create_namespace(
                client.V1Namespace(metadata=client.V1ObjectMeta(name=body.namespace))
            )
        except client.exceptions.ApiException as e:
            if e.status != 409:
                raise

        gateway_name = "maas-default-gateway"
        try:
            gws = custom.list_namespaced_custom_object(
                group="gateway.networking.k8s.io", version="v1",
                namespace="openshift-ingress", plural="gateways",
            )
            names = [g["metadata"]["name"] for g in gws.get("items", [])]
            if names and "maas-default-gateway" not in names:
                gateway_name = names[0]
        except Exception:
            pass

        if body.cpu_only:
            container_image = "ghcr.io/llm-d/llm-d-cpu:v0.7.0"
            container_env = [
                {"name": "HF_HOME", "value": "/tmp/hf_home"},
                {"name": "VLLM_TARGET_DEVICE", "value": "cpu"},
                {"name": "VLLM_CPU_KVCACHE_SPACE", "value": "4"},
            ]
            container_resources = {
                "limits": {"cpu": "64", "memory": "64Gi"},
                "requests": {"cpu": "16", "memory": "32Gi"},
            }
            tolerations = []
            vllm_args = ["--dtype", "bfloat16", "--max-model-len", "4096"]
        else:
            container_image = "vllm/vllm-openai:v0.8.4"
            vllm_extra = f"--dtype=half --max-model-len=4096 --gpu-memory-utilization=0.9 --enforce-eager --tensor-parallel-size {body.gpu_count}"
            container_env = [
                {"name": "VLLM_USE_V1", "value": "0"},
                {"name": "HF_HOME", "value": "/tmp/hf_home"},
                {"name": "VLLM_ADDITIONAL_ARGS", "value": vllm_extra},
            ]
            mem_limit = f"{12 * body.gpu_count}Gi"
            mem_request = f"{8 * body.gpu_count}Gi"
            container_resources = {
                "limits": {
                    "cpu": "2", "memory": mem_limit,
                    "nvidia.com/gpu": str(body.gpu_count),
                },
                "requests": {
                    "cpu": "1", "memory": mem_request,
                    "nvidia.com/gpu": str(body.gpu_count),
                },
            }
            tolerations = [
                {
                    "key": "nvidia.com/gpu",
                    "operator": "Exists",
                    "effect": "NoSchedule",
                }
            ]
            vllm_args = []

        container_spec = {
            "name": "main",
            "image": container_image,
            "env": container_env,
            "resources": container_resources,
        }
        if vllm_args:
            container_spec["args"] = vllm_args

        template_spec = {"containers": [container_spec]}
        if tolerations:
            template_spec["tolerations"] = tolerations

        llm_isvc = {
            "apiVersion": f"{KSERVE_GROUP}/{KSERVE_VERSION}",
            "kind": "LLMInferenceService",
            "metadata": {
                "name": body.model_name,
                "namespace": body.namespace,
                "annotations": {
                    "security.opendatahub.io/enable-auth": "true",
                },
                "labels": {
                    "opendatahub.io/dashboard": "true",
                    "opendatahub.io/genai-asset": "true",
                },
            },
            "spec": {
                "replicas": body.replicas,
                "model": {
                    "uri": f"hf://{body.model_id}",
                    "name": body.model_id,
                },
                "router": {
                    "route": {},
                    "gateway": {
                        "refs": [
                            {
                                "name": gateway_name,
                                "namespace": "openshift-ingress",
                            }
                        ]
                    },
                },
                "template": template_spec,
            },
        }

        def create_ignore_conflict(group, version, namespace, plural, body):
            try:
                custom.create_namespaced_custom_object(
                    group=group, version=version,
                    namespace=namespace, plural=plural, body=body,
                )
            except client.exceptions.ApiException as exc:
                if exc.status != 409:
                    raise

        create_ignore_conflict(
            KSERVE_GROUP, KSERVE_VERSION, body.namespace,
            "llminferenceservices", llm_isvc,
        )

        model_ref = {
            "apiVersion": f"{MAAS_GROUP}/{MAAS_VERSION}",
            "kind": "MaaSModelRef",
            "metadata": {"name": body.model_name, "namespace": body.namespace},
            "spec": {
                "modelRef": {
                    "kind": "LLMInferenceService",
                    "name": body.model_name,
                }
            },
        }
        create_ignore_conflict(
            MAAS_GROUP, MAAS_VERSION, body.namespace,
            "maasmodelrefs", model_ref,
        )

        subscription = {
            "apiVersion": f"{MAAS_GROUP}/{MAAS_VERSION}",
            "kind": "MaaSSubscription",
            "metadata": {
                "name": f"{body.model_name}-subscription",
                "namespace": "models-as-a-service",
                "annotations": {
                    "openshift.io/display-name": f"{body.model_name}-subscription",
                },
            },
            "spec": {
                "owner": {"groups": [{"name": "cluster-admins"}]},
                "modelRefs": [
                    {
                        "name": body.model_name,
                        "namespace": body.namespace,
                        "tokenRateLimits": [{"limit": 1000000, "window": "24h"}],
                    }
                ],
            },
        }
        create_ignore_conflict(
            MAAS_GROUP, MAAS_VERSION, "models-as-a-service",
            "maassubscriptions", subscription,
        )

        auth_policy = {
            "apiVersion": f"{MAAS_GROUP}/{MAAS_VERSION}",
            "kind": "MaaSAuthPolicy",
            "metadata": {
                "name": f"{body.model_name}-auth-policy",
                "namespace": "models-as-a-service",
            },
            "spec": {
                "modelRefs": [
                    {"name": body.model_name, "namespace": body.namespace}
                ],
                "subjects": {"groups": [{"name": "cluster-admins"}]},
            },
        }
        create_ignore_conflict(
            MAAS_GROUP, MAAS_VERSION, "models-as-a-service",
            "maasauthpolicies", auth_policy,
        )

        return {"ok": True, "message": f"Deployed {body.model_name} on {name}"}
    except client.exceptions.ApiException as e:
        raise HTTPException(e.status, json.loads(e.body).get("message", str(e)))
    except Exception as e:
        raise HTTPException(500, str(e))


@app.delete("/api/clusters/{cluster_name}/models/{ns}/{model_name}")
def api_delete_model(cluster_name: str, ns: str, model_name: str):
    clusters = load_clusters()
    cluster = next((c for c in clusters if c["name"] == cluster_name), None)
    if not cluster:
        raise HTTPException(404, f"Cluster '{cluster_name}' not found")
    try:
        clients = get_k8s_clients(cluster["kubeconfig"])
        custom = clients["custom"]

        custom.delete_namespaced_custom_object(
            group=KSERVE_GROUP, version=KSERVE_VERSION,
            namespace=ns, plural="llminferenceservices", name=model_name,
        )

        try:
            custom.delete_namespaced_custom_object(
                group=MAAS_GROUP, version=MAAS_VERSION,
                namespace=ns, plural="maasmodelrefs", name=model_name,
            )
        except Exception:
            pass

        try:
            custom.delete_namespaced_custom_object(
                group=MAAS_GROUP, version=MAAS_VERSION,
                namespace="models-as-a-service", plural="maassubscriptions",
                name=f"{model_name}-subscription",
            )
        except Exception:
            pass

        try:
            custom.delete_namespaced_custom_object(
                group=MAAS_GROUP, version=MAAS_VERSION,
                namespace="models-as-a-service", plural="maasauthpolicies",
                name=f"{model_name}-auth-policy",
            )
        except Exception:
            pass

        return {"ok": True, "message": f"Deleted {model_name} from {cluster_name}"}
    except client.exceptions.ApiException as e:
        raise HTTPException(e.status, json.loads(e.body).get("message", str(e)))


class ModelMove(BaseModel):
    target_cluster: str


@app.post("/api/clusters/{cluster_name}/models/{ns}/{model_name}/move")
def api_move_model(cluster_name: str, ns: str, model_name: str, body: ModelMove):
    clusters = load_clusters()
    source = next((c for c in clusters if c["name"] == cluster_name), None)
    target = next((c for c in clusters if c["name"] == body.target_cluster), None)
    if not source:
        raise HTTPException(404, f"Source cluster '{cluster_name}' not found")
    if not target:
        raise HTTPException(404, f"Target cluster '{body.target_cluster}' not found")

    try:
        src_clients = get_k8s_clients(source["kubeconfig"])
        src_custom = src_clients["custom"]
        isvc = src_custom.get_namespaced_custom_object(
            group=KSERVE_GROUP, version=KSERVE_VERSION,
            namespace=ns, plural="llminferenceservices", name=model_name,
        )
    except Exception as e:
        raise HTTPException(404, f"Model not found on source: {e}")

    spec = isvc.get("spec", {})
    model_spec = spec.get("model", {})
    model_id = model_spec.get("name", "")
    replicas = spec.get("replicas", 1)
    gpu_count = 0
    for container in spec.get("template", {}).get("containers", []):
        gpu_count = int(
            container.get("resources", {}).get("limits", {}).get("nvidia.com/gpu", 0)
        )
        if gpu_count:
            break

    deploy_body = ModelDeploy(
        model_name=model_name,
        model_id=model_id,
        namespace=ns,
        replicas=replicas,
        gpu_count=gpu_count or 1,
    )
    api_deploy_model(body.target_cluster, deploy_body)
    api_delete_model(cluster_name, ns, model_name)

    return {
        "ok": True,
        "message": f"Moved {model_name} from {cluster_name} to {body.target_cluster}",
    }


@app.get("/api/clusters/{name}/apps")
def api_list_apps(name: str):
    clusters = load_clusters()
    cluster = next((c for c in clusters if c["name"] == name), None)
    if not cluster:
        raise HTTPException(404, f"Cluster '{name}' not found")
    return list_apps(cluster)


class AppDeploy(BaseModel):
    app_name: str
    image: str
    namespace: str
    replicas: int = 1


@app.post("/api/clusters/{name}/apps")
def api_deploy_app(name: str, body: AppDeploy):
    clusters = load_clusters()
    cluster = next((c for c in clusters if c["name"] == name), None)
    if not cluster:
        raise HTTPException(404, f"Cluster '{name}' not found")
    try:
        clients = get_k8s_clients(cluster["kubeconfig"])
        core = clients["core"]
        apps_api = client.AppsV1Api(clients["api_client"])

        try:
            core.create_namespace(
                client.V1Namespace(metadata=client.V1ObjectMeta(name=body.namespace))
            )
        except client.exceptions.ApiException as e:
            if e.status != 409:
                raise

        deployment = client.V1Deployment(
            metadata=client.V1ObjectMeta(
                name=body.app_name,
                namespace=body.namespace,
                labels={GRID_LABEL: "true"},
            ),
            spec=client.V1DeploymentSpec(
                replicas=body.replicas,
                selector=client.V1LabelSelector(
                    match_labels={"app": body.app_name},
                ),
                template=client.V1PodTemplateSpec(
                    metadata=client.V1ObjectMeta(
                        labels={"app": body.app_name, GRID_LABEL: "true"},
                    ),
                    spec=client.V1PodSpec(
                        containers=[
                            client.V1Container(
                                name="main",
                                image=body.image,
                                ports=[client.V1ContainerPort(container_port=8080)],
                            )
                        ]
                    ),
                ),
            ),
        )
        apps_api.create_namespaced_deployment(
            namespace=body.namespace, body=deployment,
        )

        service = client.V1Service(
            metadata=client.V1ObjectMeta(
                name=body.app_name,
                namespace=body.namespace,
                labels={GRID_LABEL: "true"},
            ),
            spec=client.V1ServiceSpec(
                selector={"app": body.app_name},
                ports=[client.V1ServicePort(port=8080, target_port=8080)],
            ),
        )
        try:
            core.create_namespaced_service(namespace=body.namespace, body=service)
        except client.exceptions.ApiException as e:
            if e.status != 409:
                raise

        route_url = None
        try:
            route_body = {
                "apiVersion": "route.openshift.io/v1",
                "kind": "Route",
                "metadata": {
                    "name": body.app_name,
                    "namespace": body.namespace,
                    "labels": {GRID_LABEL: "true"},
                },
                "spec": {
                    "to": {"kind": "Service", "name": body.app_name, "weight": 100},
                    "port": {"targetPort": 8080},
                    "tls": {"termination": "edge", "insecureEdgeTerminationPolicy": "Redirect"},
                },
            }
            created_route = clients["custom"].create_namespaced_custom_object(
                group="route.openshift.io", version="v1",
                namespace=body.namespace, plural="routes",
                body=route_body,
            )
            route_host = created_route.get("spec", {}).get("host", "")
            if route_host:
                route_url = f"https://{route_host}"
        except client.exceptions.ApiException as e:
            if e.status != 409:
                pass

        result = {"ok": True, "message": f"Deployed app {body.app_name} on {name}"}
        if route_url:
            result["route_url"] = route_url
        return result
    except client.exceptions.ApiException as e:
        raise HTTPException(e.status, json.loads(e.body).get("message", str(e)))
    except Exception as e:
        raise HTTPException(500, str(e))


@app.delete("/api/clusters/{cluster_name}/apps/{ns}/{app_name}")
def api_delete_app(cluster_name: str, ns: str, app_name: str):
    clusters = load_clusters()
    cluster = next((c for c in clusters if c["name"] == cluster_name), None)
    if not cluster:
        raise HTTPException(404, f"Cluster '{cluster_name}' not found")
    try:
        clients = get_k8s_clients(cluster["kubeconfig"])
        apps_api = client.AppsV1Api(clients["api_client"])
        core = clients["core"]

        apps_api.delete_namespaced_deployment(name=app_name, namespace=ns)
        try:
            core.delete_namespaced_service(name=app_name, namespace=ns)
        except Exception:
            pass
        try:
            clients["custom"].delete_namespaced_custom_object(
                group="route.openshift.io", version="v1",
                namespace=ns, plural="routes", name=app_name,
            )
        except Exception:
            pass
        return {"ok": True, "message": f"Deleted app {app_name}"}
    except client.exceptions.ApiException as e:
        raise HTTPException(e.status, json.loads(e.body).get("message", str(e)))


def load_spreads():
    if not SPREADS_FILE.exists():
        return []
    with open(SPREADS_FILE) as f:
        return json.load(f)


def save_spreads(spreads):
    with open(SPREADS_FILE, "w") as f:
        json.dump(spreads, f, indent=2)


def verify_spread(spread, clusters_data):
    hub_cluster = next((c for c in clusters_data if c["name"] == spread["hub"]), None)
    if not hub_cluster:
        return False
    try:
        clients = get_k8s_clients(hub_cluster["kubeconfig"])
        custom = clients["custom"]
        ns = "aig-routing"
        route_ok = False
        try:
            routes = custom.list_namespaced_custom_object(
                group="route.openshift.io", version="v1",
                namespace=ns, plural="routes",
                _request_timeout=K8S_TIMEOUT,
            ).get("items", [])
            for r in routes:
                svc = r.get("spec", {}).get("to", {}).get("name", "")
                admitted = any(
                    c.get("type") == "Admitted" and c.get("status") == "True"
                    for ing in r.get("status", {}).get("ingress", [])
                    for c in ing.get("conditions", [])
                )
                if svc and admitted:
                    route_ok = True
                    break
        except Exception:
            pass
        if not route_ok:
            return False
        providers = custom.list_namespaced_custom_object(
            group="inference.opendatahub.io", version="v1alpha1",
            namespace=ns, plural="externalproviders",
            _request_timeout=K8S_TIMEOUT,
        ).get("items", [])
        ready_providers = set()
        for ep in providers:
            conditions = ep.get("status", {}).get("conditions", [])
            if any(c.get("type") == "Ready" and c.get("status") == "True" for c in conditions):
                ready_providers.add(ep["metadata"]["name"])
        for spoke in spread["spokes"]:
            if spoke not in ready_providers:
                return False
        return True
    except Exception:
        return False


@app.get("/api/spreads")
def api_list_spreads():
    spreads = load_spreads()
    clusters_data = load_clusters()
    for s in spreads:
        s["verified"] = verify_spread(s, clusters_data)
    return spreads


class SpreadCreate(BaseModel):
    model_name: str
    model_namespace: str
    model_id: str
    hub: str
    spokes: list[str]


@app.post("/api/spreads")
def api_create_spread(body: SpreadCreate):
    clusters_data = load_clusters()
    cluster_names = {c["name"]: c for c in clusters_data}

    hub_cluster = cluster_names.get(body.hub)
    if not hub_cluster:
        raise HTTPException(404, f"Hub cluster '{body.hub}' not found")
    if "hub" not in hub_cluster.get("tags", []):
        raise HTTPException(400, f"Cluster '{body.hub}' is not tagged as hub")

    for spoke in body.spokes:
        if spoke not in cluster_names:
            raise HTTPException(404, f"Spoke cluster '{spoke}' not found")
    if len(set(body.spokes)) != len(body.spokes):
        raise HTTPException(400, "Duplicate spokes")
    if not body.spokes:
        raise HTTPException(400, "At least one spoke required")

    sorted_spokes = sorted(body.spokes)
    spread_id = hashlib.md5(
        f"{body.model_name}-{body.hub}-{'-'.join(sorted_spokes)}".encode()
    ).hexdigest()[:8]

    existing = load_spreads()
    if any(s["id"] == spread_id for s in existing):
        raise HTTPException(409, "This spread already exists")

    spread_entry = {
        "id": spread_id,
        "model_id": body.model_id,
        "model_name": body.model_name,
        "model_namespace": body.model_namespace,
        "hub": body.hub,
        "spokes": sorted_spokes,
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
    }
    existing.append(spread_entry)
    save_spreads(existing)
    return {"ok": True, "spread": spread_entry}


@app.delete("/api/spreads/{spread_id}")
def api_delete_spread(spread_id: str):
    spreads = load_spreads()
    if not any(s["id"] == spread_id for s in spreads):
        raise HTTPException(404, "Spread not found")
    spreads = [s for s in spreads if s["id"] != spread_id]
    save_spreads(spreads)
    return {"ok": True}


@app.get("/api/spreads/{spread_id}/metrics")
def api_spread_metrics(spread_id: str):
    spreads = load_spreads()
    spread = next((s for s in spreads if s["id"] == spread_id), None)
    if not spread:
        raise HTTPException(404, "Spread not found")

    clusters_data = load_clusters()
    cluster_map = {c["name"]: c for c in clusters_data}

    hub_cluster = cluster_map.get(spread["hub"])
    hub_url = _get_cached_hub_url(hub_cluster) if hub_cluster else ""

    def spoke_metrics(spoke_name):
        cluster = cluster_map.get(spoke_name)
        result = {
            "name": spoke_name,
            "display_name": cluster.get("display_name", spoke_name) if cluster else spoke_name,
            "ready_pods": 0,
            "avg_latency_ms": 0.0,
            "req_rate": 0.0,
            "tokens_per_sec": 0.0,
            "total_requests": 0,
            "region": "",
            "reachable": False,
        }
        if not cluster:
            return result
        try:
            query_instant, _ = _get_cached_thanos(cluster)
            ns = spread["model_namespace"]
            model = spread["model_name"]

            queries = {
                "pods": f'count(up{{namespace="{ns}",job=~".*{model}.*"}}==1)',
                "latency": (
                    f'rate(vllm:e2e_request_latency_seconds_sum{{namespace="{ns}"}}[5m])'
                    f' / rate(vllm:e2e_request_latency_seconds_count{{namespace="{ns}"}}[5m])'
                ),
                "req_rate": f'sum(rate(vllm:request_success_total{{namespace="{ns}"}}[5m]))',
                "tps": f'sum(rate(vllm:generation_tokens_total{{namespace="{ns}"}}[5m]))',
                "total": f'sum(vllm:request_success_total{{namespace="{ns}"}})',
            }

            def run_query(item):
                key, promql = item
                try:
                    return key, query_instant(promql)
                except Exception:
                    return key, []

            with ThreadPoolExecutor(max_workers=5) as qpool:
                raw = dict(qpool.map(run_query, queries.items()))

            if raw["pods"]:
                result["ready_pods"] = int(float(raw["pods"][0]["value"][1]))
            for key, field, scale in [
                ("latency", "avg_latency_ms", 1000),
                ("req_rate", "req_rate", 60),
                ("tps", "tokens_per_sec", 1),
                ("total", "total_requests", 1),
            ]:
                v = raw.get(key)
                if v and v[0]["value"][1] != "NaN":
                    val = float(v[0]["value"][1]) * scale
                    result[field] = int(val) if key == "total" else round(val, 1)

            result["reachable"] = True
            result["region"] = _get_cached_region(cluster)
        except Exception:
            pass
        return result

    with ThreadPoolExecutor(max_workers=4) as pool:
        spoke_results = list(pool.map(spoke_metrics, spread["spokes"]))

    scores = []
    for s in spoke_results:
        latency_penalty = min(s["avg_latency_ms"] / 1000, 3)
        score = round(max(4 - latency_penalty, 1), 2)
        scores.append(score)

    max_score = max(scores) if scores else 0
    best_indices = [i for i, sc in enumerate(scores) if sc == max_score]
    best_idx = best_indices[int(time.time()) % len(best_indices)] if best_indices else 0
    return {
        "spread": spread,
        "hub_url": hub_url,
        "spokes": spoke_results,
        "scores": scores,
        "route_to": spoke_results[best_idx]["name"] if spoke_results else "",
    }


@app.get("/api/spreads/traffic")
def api_spreads_traffic():
    spreads = load_spreads()
    clusters_data = load_clusters()
    cluster_map = {c["name"]: c for c in clusters_data}

    all_spoke_queries = []
    for spread in spreads:
        for spoke_name in spread["spokes"]:
            cluster = cluster_map.get(spoke_name)
            if cluster:
                all_spoke_queries.append((spread["id"], spoke_name, cluster, spread["model_namespace"]))

    def query_spoke_rate(item):
        spread_id, spoke_name, cluster, ns = item
        try:
            qi, _ = _get_cached_thanos(cluster)
            result = qi(f'sum(rate(vllm:request_success_total{{namespace="{ns}"}}[5m]))')
            if result and result[0]["value"][1] != "NaN":
                return spread_id, spoke_name, round(float(result[0]["value"][1]) * 60, 1)
        except Exception:
            pass
        return spread_id, spoke_name, 0.0

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(query_spoke_rate, all_spoke_queries))

    traffic = {}
    for spread_id, spoke_name, req_rate in results:
        traffic.setdefault(spread_id, {})[spoke_name] = {"req_rate": req_rate}

    for spread in spreads:
        if spread["id"] not in traffic:
            traffic[spread["id"]] = {}
        for spoke_name in spread["spokes"]:
            if spoke_name not in traffic[spread["id"]]:
                traffic[spread["id"]][spoke_name] = {"req_rate": 0.0}

    return {"spreads": traffic}


@app.get("/api/metrics/summary")
def api_metrics_summary():
    clusters_list = load_clusters()

    def gather_metrics(cluster):
        result = {
            "gpu_count": 0, "gpu_util_sum": 0, "gpu_util_count": 0,
            "model_count": 0, "tokens_per_sec": None,
        }
        try:
            clients = get_k8s_clients(cluster["kubeconfig"])
            core = clients["core"]
            custom = clients["custom"]

            nodes = core.list_node(_request_timeout=K8S_TIMEOUT)
            for node in nodes.items:
                alloc = node.status.allocatable or {}
                result["gpu_count"] += int(alloc.get("nvidia.com/gpu", "0"))

            try:
                query_instant, _ = get_thanos_querier(cluster)
                gpu_results = query_instant("DCGM_FI_DEV_GPU_UTIL")
                for r in gpu_results:
                    val = float(r["value"][1])
                    result["gpu_util_sum"] += val
                    result["gpu_util_count"] += 1

                tps_results = query_instant("sum(rate(vllm:generation_tokens_total[5m]))")
                if tps_results and tps_results[0]["value"][1] != "NaN":
                    result["tokens_per_sec"] = float(tps_results[0]["value"][1])
            except Exception:
                pass

            try:
                items = custom.list_cluster_custom_object(
                    group=KSERVE_GROUP, version=KSERVE_VERSION,
                    plural="llminferenceservices",
                    _request_timeout=K8S_TIMEOUT,
                ).get("items", [])
                result["model_count"] = len(items)
            except Exception:
                pass

        except Exception:
            pass
        return result

    with ThreadPoolExecutor(max_workers=max(len(clusters_list), 1)) as pool:
        results = list(pool.map(gather_metrics, clusters_list))

    total_gpus = sum(r["gpu_count"] for r in results)
    total_util_sum = sum(r["gpu_util_sum"] for r in results)
    total_util_count = sum(r["gpu_util_count"] for r in results)
    total_models = sum(r["model_count"] for r in results)
    tps_values = [r["tokens_per_sec"] for r in results if r["tokens_per_sec"] is not None]

    return {
        "total_gpus": total_gpus,
        "gpu_utilization_pct": round(total_util_sum / total_util_count, 1) if total_util_count else None,
        "active_models": total_models,
        "active_clusters": len([r for r in results if r["gpu_count"] > 0 or r["model_count"] > 0]),
        "tokens_per_sec": round(sum(tps_values), 1) if tps_values else None,
    }


@app.get("/api/metrics/timeseries")
def api_metrics_timeseries(window: str = Query("1h", pattern="^(1h|6h|24h)$")):
    duration_map = {"1h": 3600, "6h": 21600, "24h": 86400}
    step_map = {"1h": "60", "6h": "300", "24h": "900"}

    duration = duration_map[window]
    step = step_map[window]
    end_time = time.time()
    start_time = end_time - duration

    clusters_list = load_clusters()

    queries = {
        "gpu_utilization": "avg(DCGM_FI_DEV_GPU_UTIL)",
        "tokens_per_sec": "sum(rate(vllm:generation_tokens_total[5m]))",
        "queue_depth": "sum(vllm:num_requests_waiting)",
    }

    def fetch_cluster_series(cluster):
        cluster_results = {}
        try:
            _, query_range = get_thanos_querier(cluster)
            for metric_name, promql in queries.items():
                try:
                    results = query_range(promql, start_time, end_time, step)
                    points = []
                    for r in results:
                        for ts, val in r.get("values", []):
                            if val != "NaN":
                                points.append((float(ts), float(val)))
                    cluster_results[metric_name] = points
                except Exception:
                    cluster_results[metric_name] = []
        except Exception:
            for k in queries:
                cluster_results[k] = []
        return cluster_results

    with ThreadPoolExecutor(max_workers=max(len(clusters_list), 1)) as pool:
        all_results = list(pool.map(fetch_cluster_series, clusters_list))

    series = {k: {} for k in queries}
    for cluster_data in all_results:
        for metric_name, points in cluster_data.items():
            for ts, val in points:
                ts_key = int(ts)
                if ts_key not in series[metric_name]:
                    series[metric_name][ts_key] = []
                series[metric_name][ts_key].append(val)

    output = {}
    for metric_name in queries:
        sorted_ts = sorted(series[metric_name].keys())
        timestamps = []
        values = []
        for ts in sorted_ts:
            timestamps.append(ts)
            vals = series[metric_name][ts]
            if metric_name == "gpu_utilization":
                values.append(round(sum(vals) / len(vals), 1))
            else:
                values.append(round(sum(vals), 1))
        output[metric_name] = {"timestamps": timestamps, "values": values}

    return output


app.mount("/", StaticFiles(directory=Path(__file__).parent / "static", html=True))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8501)
