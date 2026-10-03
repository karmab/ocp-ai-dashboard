import json
import shutil
from pathlib import Path

from fastapi import HTTPException, Query
from pydantic import BaseModel

from demo import generators

_data_dir = None
_seed_dir = None
_clusters_file = None
_spreads_file = None
_models_store = {}
_apps_store = {}


class _ClusterCreate(BaseModel):
    name: str
    display_name: str
    kubeconfig_path: str
    lat: float
    lon: float


class _ModelDeploy(BaseModel):
    model_name: str
    model_id: str
    namespace: str
    replicas: int = 1
    gpu_count: int = 1
    cpu_only: bool = False


class _ModelMove(BaseModel):
    target_cluster: str


class _AppDeploy(BaseModel):
    app_name: str
    image: str
    namespace: str
    replicas: int = 1


class _ScenarioUpdate(BaseModel):
    cluster_overrides: dict = {}
    traffic_multipliers: dict = {}


def _load_clusters():
    if not _clusters_file.exists():
        return []
    with open(_clusters_file) as f:
        return json.load(f)


def _save_clusters(clusters):
    with open(_clusters_file, "w") as f:
        json.dump(clusters, f, indent=2)


def _load_spreads():
    if not _spreads_file.exists():
        return []
    with open(_spreads_file) as f:
        return json.load(f)


def _init_stores():
    global _models_store, _apps_store

    models_file = _data_dir / "models.json"
    if models_file.exists():
        with open(models_file) as f:
            _models_store.clear()
            _models_store.update(json.load(f))
    else:
        _models_store.clear()

    apps_file = _data_dir / "apps.json"
    if apps_file.exists():
        with open(apps_file) as f:
            _apps_store.clear()
            _apps_store.update(json.load(f))
    else:
        _apps_store.clear()


def install_demo_routes(app, data_dir, seed_dir):
    global _data_dir, _seed_dir, _clusters_file, _spreads_file
    _data_dir = Path(data_dir)
    _seed_dir = Path(seed_dir)
    _data_dir.mkdir(parents=True, exist_ok=True)
    for f in _seed_dir.glob("*.json"):
        dest = _data_dir / f.name
        if not dest.exists():
            shutil.copy(f, dest)
    _clusters_file = _data_dir / "clusters.json"
    _spreads_file = _data_dir / "spreads.json"
    _init_stores()

    n_existing = len(app.router.routes)

    # --- Story 1: Fleet Discovery ---

    @app.get("/api/clusters/{name}/status")
    def demo_cluster_status(name: str):
        clusters = _load_clusters()
        c = next((c for c in clusters if c["name"] == name), None)
        if not c:
            raise HTTPException(404, f"Cluster '{name}' not found")
        return generators.generate_cluster_status(name, c)

    @app.get("/api/clusters/{name}/details")
    def demo_cluster_details(name: str):
        clusters = _load_clusters()
        c = next((c for c in clusters if c["name"] == name), None)
        if not c:
            raise HTTPException(404, f"Cluster '{name}' not found")
        return generators.generate_cluster_details(name, c)

    # --- Story 2: Cluster Management ---

    @app.post("/api/clusters")
    def demo_add_cluster(body: _ClusterCreate):
        clusters = _load_clusters()
        if any(c["name"] == body.name for c in clusters):
            raise HTTPException(400, f"Cluster '{body.name}' already exists")
        entry = {
            "name": body.name,
            "display_name": body.display_name,
            "kubeconfig": body.kubeconfig_path,
            "lat": body.lat,
            "lon": body.lon,
            "tags": [],
        }
        clusters.append(entry)
        _save_clusters(clusters)
        return {"ok": True, "cluster": entry}

    # --- Story 3: Model Deployment ---

    @app.get("/api/clusters/{name}/models")
    def demo_list_models(name: str):
        clusters = _load_clusters()
        if not any(c["name"] == name for c in clusters):
            raise HTTPException(404, f"Cluster '{name}' not found")
        return list(_models_store.get(name, []))

    @app.post("/api/clusters/{name}/models")
    def demo_deploy_model(name: str, body: _ModelDeploy):
        clusters = _load_clusters()
        if not any(c["name"] == name for c in clusters):
            raise HTTPException(404, f"Cluster '{name}' not found")
        if name not in _models_store:
            _models_store[name] = []
        _models_store[name].append({
            "name": body.model_name,
            "namespace": body.namespace,
            "model_id": body.model_id,
            "replicas": body.replicas,
            "gpu_per_replica": 0 if body.cpu_only else body.gpu_count,
            "ready": False,
            "status": "Progressing",
        })
        return {"ok": True, "message": f"Deployed {body.model_name} on {name}"}

    # --- Story 4: Model Lifecycle ---

    @app.delete("/api/clusters/{cluster_name}/models/{ns}/{model_name}")
    def demo_delete_model(cluster_name: str, ns: str, model_name: str):
        clusters = _load_clusters()
        if not any(c["name"] == cluster_name for c in clusters):
            raise HTTPException(404, f"Cluster '{cluster_name}' not found")
        models = _models_store.get(cluster_name, [])
        model = next(
            (m for m in models if m["name"] == model_name and m["namespace"] == ns),
            None,
        )
        if not model:
            raise HTTPException(404, f"Model '{model_name}' not found")
        _models_store[cluster_name] = [
            m for m in models
            if not (m["name"] == model_name and m["namespace"] == ns)
        ]
        return {"ok": True, "message": f"Deleted {model_name} from {cluster_name}"}

    @app.post("/api/clusters/{cluster_name}/models/{ns}/{model_name}/move")
    def demo_move_model(cluster_name: str, ns: str, model_name: str, body: _ModelMove):
        clusters = _load_clusters()
        if not any(c["name"] == cluster_name for c in clusters):
            raise HTTPException(404, f"Source cluster '{cluster_name}' not found")
        if not any(c["name"] == body.target_cluster for c in clusters):
            raise HTTPException(404, f"Target cluster '{body.target_cluster}' not found")
        models = _models_store.get(cluster_name, [])
        model = next(
            (m for m in models if m["name"] == model_name and m["namespace"] == ns),
            None,
        )
        if not model:
            raise HTTPException(404, "Model not found on source")
        _models_store[cluster_name] = [
            m for m in models
            if not (m["name"] == model_name and m["namespace"] == ns)
        ]
        if body.target_cluster not in _models_store:
            _models_store[body.target_cluster] = []
        _models_store[body.target_cluster].append(dict(model))
        return {
            "ok": True,
            "message": f"Moved {model_name} from {cluster_name} to {body.target_cluster}",
        }

    # --- Story 5: App Deployment ---

    @app.get("/api/clusters/{name}/apps")
    def demo_list_apps(name: str):
        clusters = _load_clusters()
        if not any(c["name"] == name for c in clusters):
            raise HTTPException(404, f"Cluster '{name}' not found")
        return list(_apps_store.get(name, []))

    @app.post("/api/clusters/{name}/apps")
    def demo_deploy_app(name: str, body: _AppDeploy):
        clusters = _load_clusters()
        if not any(c["name"] == name for c in clusters):
            raise HTTPException(404, f"Cluster '{name}' not found")
        route_url = f"https://{body.app_name}-{body.namespace}.apps.{name}.example.com"
        if name not in _apps_store:
            _apps_store[name] = []
        _apps_store[name].append({
            "name": body.app_name,
            "namespace": body.namespace,
            "image": body.image,
            "replicas": body.replicas,
            "ready_replicas": body.replicas,
            "ready": True,
            "route_url": route_url,
        })
        return {
            "ok": True,
            "message": f"Deployed app {body.app_name} on {name}",
            "route_url": route_url,
        }

    @app.delete("/api/clusters/{cluster_name}/apps/{ns}/{app_name}")
    def demo_delete_app(cluster_name: str, ns: str, app_name: str):
        clusters = _load_clusters()
        if not any(c["name"] == cluster_name for c in clusters):
            raise HTTPException(404, f"Cluster '{cluster_name}' not found")
        apps = _apps_store.get(cluster_name, [])
        app_entry = next(
            (a for a in apps if a["name"] == app_name and a["namespace"] == ns),
            None,
        )
        if not app_entry:
            raise HTTPException(404, f"App '{app_name}' not found")
        _apps_store[cluster_name] = [
            a for a in apps
            if not (a["name"] == app_name and a["namespace"] == ns)
        ]
        return {"ok": True, "message": f"Deleted app {app_name}"}

    # --- Story 6: Cross-Cluster Spread ---

    @app.get("/api/spreads")
    def demo_list_spreads():
        spreads = _load_spreads()
        for s in spreads:
            s["verified"] = True
        return spreads

    # --- Story 7: Live Traffic ---

    @app.get("/api/spreads/traffic")
    def demo_spreads_traffic():
        spreads = _load_spreads()
        traffic = {}
        for spread in spreads:
            traffic[spread["id"]] = {}
            for spoke in spread["spokes"]:
                rate = generators.generate_traffic_rate(spread["id"], spoke)
                traffic[spread["id"]][spoke] = {"req_rate": rate}
        return {"spreads": traffic}

    @app.get("/api/spreads/{spread_id}/metrics")
    def demo_spread_metrics(spread_id: str):
        spreads = _load_spreads()
        spread = next((s for s in spreads if s["id"] == spread_id), None)
        if not spread:
            raise HTTPException(404, "Spread not found")

        clusters_data = _load_clusters()
        cluster_map = {c["name"]: c for c in clusters_data}

        spokes = []
        scores = []
        for spoke_name in spread["spokes"]:
            cluster = cluster_map.get(spoke_name)
            metrics = generators.generate_spoke_metrics(spread, spoke_name, cluster)
            spokes.append(metrics)
            latency_penalty = min(metrics["avg_latency_ms"] / 1000, 3)
            score = round(max(4 - latency_penalty, 1), 2)
            scores.append(score)

        best_idx = scores.index(max(scores)) if scores else 0
        hub_url = f"https://maas-gateway.apps.{spread['hub']}.example.com"

        return {
            "spread": spread,
            "hub_url": hub_url,
            "spokes": spokes,
            "scores": scores,
            "route_to": spokes[best_idx]["name"] if spokes else "",
        }

    # --- Story 8: Fleet Metrics ---

    @app.get("/api/metrics/summary")
    def demo_metrics_summary():
        clusters_data = _load_clusters()
        return generators.generate_metrics_summary(_models_store, clusters_data)

    @app.get("/api/metrics/timeseries")
    def demo_timeseries(window: str = Query("1h", pattern="^(1h|6h|24h)$")):
        return generators.generate_timeseries(window)

    # --- Demo Scenario & Guide ---

    @app.get("/api/demo/status")
    def demo_status():
        return {"active": True}

    @app.post("/api/demo/scenario")
    def demo_set_scenario(body: _ScenarioUpdate):
        generators.set_scenario(body.model_dump())
        return {"ok": True}

    @app.delete("/api/demo/scenario")
    def demo_clear_scenario():
        generators.clear_scenario()
        return {"ok": True}

    @app.get("/demo-guide.js")
    def demo_guide_js():
        guide_path = _seed_dir.parent / "demo-guide.js"
        from fastapi.responses import Response
        return Response(content=guide_path.read_text(), media_type="application/javascript")

    # --- Demo Reset ---

    @app.post("/api/demo/reset")
    def demo_reset():
        for f in _seed_dir.glob("*.json"):
            shutil.copy(f, _data_dir / f.name)
        _init_stores()
        generators.clear_scenario()
        return {"ok": True}

    # Reorder: demo routes first so they match before originals
    demo_routes = list(app.router.routes[n_existing:])
    original_routes = list(app.router.routes[:n_existing])
    app.router.routes.clear()
    app.router.routes.extend(demo_routes)
    app.router.routes.extend(original_routes)
