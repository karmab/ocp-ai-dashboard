import hashlib
import math
import time


_CLUSTER_PROFILES = {
    "vai": {
        "health": "green", "health_details": "healthy",
        "gpu_count": 8, "gpu_avg": 68.5,
        "region": "westus", "platform": "Azure", "ocp_version": "4.18.6",
    },
    "satch": {
        "health": "yellow", "health_details": "GPU avg 92%",
        "gpu_count": 4, "gpu_avg": 92.1,
        "region": "us-west-2", "platform": "AWS", "ocp_version": "4.17.12",
    },
    "bumblefoot": {
        "health": "green", "health_details": "GPU avg 45%",
        "gpu_count": 4, "gpu_avg": 45.3,
        "region": "us-east-1", "platform": "libvirt", "ocp_version": "4.18.2",
    },
}

_DEFAULT_PROFILE = {
    "health": "green", "health_details": "healthy",
    "gpu_count": 4, "gpu_avg": 55.0,
    "region": "us-east-1", "platform": "BareMetal", "ocp_version": "4.18.6",
}

_scenario = {
    "cluster_overrides": {},
    "traffic_multipliers": {},
}


def set_scenario(overrides):
    _scenario["cluster_overrides"] = overrides.get("cluster_overrides", {})
    _scenario["traffic_multipliers"] = overrides.get("traffic_multipliers", {})


def clear_scenario():
    _scenario["cluster_overrides"].clear()
    _scenario["traffic_multipliers"].clear()

_RHOAI_COMPONENTS = {
    "Red Hat OpenShift AI": {"version": "2.19.0", "phase": "Succeeded"},
    "OpenShift Serverless": {"version": "1.35.0", "phase": "Succeeded"},
    "OpenShift Service Mesh": {"version": "2.6.3", "phase": "Succeeded"},
    "Authorino Operator": {"version": "1.1.0", "phase": "Succeeded"},
    "KServe": {"version": "0.14.1", "phase": "Succeeded"},
}


def _seed_for(name):
    return int(hashlib.md5(name.encode()).hexdigest()[:8], 16)


def _get_profile(cluster_name):
    base = dict(_CLUSTER_PROFILES.get(cluster_name, _DEFAULT_PROFILE))
    overrides = _scenario["cluster_overrides"].get(cluster_name, {})
    base.update(overrides)
    return base


def generate_cluster_status(cluster_name, cluster_data):
    profile = _get_profile(cluster_name)
    reachable = profile.get("reachable", True)

    nodes = []
    for i in range(5):
        roles = ["master"] if i < 3 else ["worker"]
        if i < 3:
            ready = reachable
        else:
            ready = _worker_ready(profile, i - 3)
        nodes.append({
            "name": f"{cluster_name}-node-{i}",
            "roles": roles,
            "ready": ready,
        })

    ready_count = sum(1 for n in nodes if n["ready"])

    return {
        "reachable": reachable,
        "nodes": nodes,
        "node_count": len(nodes),
        "ready_nodes": ready_count,
        "region": profile["region"],
        "detected_lat": cluster_data.get("lat", 0),
        "detected_lon": cluster_data.get("lon", 0),
        "health": profile["health"],
        "health_details": profile["health_details"],
        "gpu_avg": profile["gpu_avg"],
        "gpu_count": profile["gpu_count"],
    }


def _worker_ready(profile, worker_index):
    health = profile["health"]
    reachable = profile.get("reachable", True)
    if not reachable:
        return False
    if health == "red":
        return False
    if health == "yellow" and worker_index == 1:
        return False
    return True


def generate_cluster_details(cluster_name, cluster_data):
    profile = _get_profile(cluster_name)
    region = profile["region"]

    instance_types = {
        "AWS": ("m5.2xlarge", "p3.8xlarge"),
        "Azure": ("Standard_D8s_v3", "Standard_NC24ads_A100_v4"),
        "GCP": ("n1-standard-8", "a2-highgpu-4g"),
        "libvirt": ("", ""),
        "BareMetal": ("", ""),
    }
    master_type, worker_type = instance_types.get(profile["platform"], ("", ""))
    gpu_per_worker = max(1, profile["gpu_count"] // 2)

    topology = [
        {"name": f"{cluster_name}-master-{i}", "roles": ["master"], "ready": True,
         "cpu": "8", "memory": "32Gi", "gpu": "0", "instance_type": master_type,
         "zone": f"{region}{'ab'[i % 2]}", "arch": "amd64"}
        for i in range(3)
    ] + [
        {"name": f"{cluster_name}-worker-{i}", "roles": ["worker"],
         "ready": _worker_ready(profile, i),
         "cpu": "16", "memory": "64Gi", "gpu": str(gpu_per_worker),
         "instance_type": worker_type,
         "zone": f"{region}{'ab'[i % 2]}", "arch": "amd64"}
        for i in range(2)
    ]

    return {
        "ocp_version": profile["ocp_version"],
        "platform": profile["platform"],
        "topology": topology,
        "rhoai_components": {k: dict(v) for k, v in _RHOAI_COMPONENTS.items()},
    }


def generate_traffic_rate(spread_id, spoke_name):
    seed = _seed_for(f"{spread_id}:{spoke_name}")
    base_rate = 15 + (seed % 50)
    t = time.time()
    phase = seed / 1000.0
    drift = math.sin(t / 30.0 + phase) * 3
    rate = max(0.1, base_rate + drift)
    multiplier = _scenario["traffic_multipliers"].get(spoke_name, 1.0)
    return round(max(0, rate * multiplier), 1)


def generate_spoke_metrics(spread, spoke_name, cluster_data):
    seed = _seed_for(f"{spread['id']}:{spoke_name}")
    profile = _get_profile(spoke_name)
    reachable = profile.get("reachable", True)

    base_latency = 50 + (seed % 350)
    latency_override = _scenario["cluster_overrides"].get(spoke_name, {}).get("latency_ms")
    latency = latency_override if latency_override is not None else base_latency

    multiplier = _scenario["traffic_multipliers"].get(spoke_name, 1.0)
    ready_pods = 0 if not reachable else max(0, 1 + (seed % 3))

    return {
        "name": spoke_name,
        "display_name": cluster_data.get("display_name", spoke_name) if cluster_data else spoke_name,
        "ready_pods": ready_pods,
        "avg_latency_ms": float(latency),
        "req_rate": generate_traffic_rate(spread["id"], spoke_name),
        "tokens_per_sec": round((10 + (seed % 190)) * multiplier, 1),
        "total_requests": 1000 + (seed % 49000),
        "region": profile["region"],
        "reachable": reachable,
    }


def generate_metrics_summary(models_store, clusters_data):
    total_models = sum(len(models) for models in models_store.values())

    total_gpus = 0
    gpu_util_weighted = 0
    for c in clusters_data:
        profile = _get_profile(c["name"])
        count = profile["gpu_count"]
        total_gpus += count
        gpu_util_weighted += count * profile["gpu_avg"]

    multipliers = _scenario["traffic_multipliers"]
    if multipliers:
        traffic_factor = min(sum(multipliers.values()) / len(multipliers), 1.0)
    else:
        traffic_factor = 1.0

    base_tps = 1847.2
    if total_gpus:
        avg_util = gpu_util_weighted / total_gpus
        base_util = 68.6
        tps = base_tps * (avg_util / base_util) * traffic_factor if base_util else base_tps
    else:
        tps = 0

    return {
        "total_gpus": total_gpus,
        "gpu_utilization_pct": round(gpu_util_weighted / total_gpus, 1) if total_gpus else None,
        "active_models": total_models,
        "active_clusters": len(clusters_data),
        "tokens_per_sec": round(tps, 1),
    }


def generate_timeseries(window):
    duration_map = {"1h": 3600, "6h": 21600, "24h": 86400}
    step_map = {"1h": 60, "6h": 300, "24h": 900}

    duration = duration_map[window]
    step = step_map[window]
    end_time = int(time.time())
    start_time = end_time - duration
    num_points = duration // step

    timestamps = [start_time + i * step for i in range(num_points)]

    gpu_values = []
    tps_values = []
    qd_values = []

    for ts in timestamps:
        gpu = 70 + 15 * math.sin(ts / 600.0) + 3 * math.sin(ts / 47.0 + 1.5)
        gpu_values.append(round(max(0, min(100, gpu)), 1))

        tps = 1600 + 700 * math.sin(ts / 900.0 + 0.7) + 100 * math.sin(ts / 37.0 + 2.1)
        tps_values.append(round(max(0, tps), 1))

        qd = 1.5 + 2 * max(0, math.sin(ts / 400.0)) + 5 * max(0, math.sin(ts / 1800.0)) ** 4
        qd_values.append(round(max(0, qd), 1))

    return {
        "gpu_utilization": {"timestamps": timestamps, "values": gpu_values},
        "tokens_per_sec": {"timestamps": timestamps, "values": tps_values},
        "queue_depth": {"timestamps": timestamps, "values": qd_values},
    }
