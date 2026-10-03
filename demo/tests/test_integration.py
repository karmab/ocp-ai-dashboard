"""Integration tests: cross-story workflows and demo isolation guarantees."""
import os
from pathlib import Path


class TestDemoModeToggle:
    def test_demo_mode_env_var_is_set(self, demo_client, monkeypatch):
        assert os.environ.get("GRID_DEMO_MODE") == "true"

    def test_non_demo_mode_hits_real_endpoints(self, demo_data_dir, monkeypatch):
        """With GRID_DEMO_MODE unset, status calls should fail (no real clusters)."""
        monkeypatch.delenv("GRID_DEMO_MODE", raising=False)
        monkeypatch.setenv("GRID_DATA_DIR", str(demo_data_dir))

        import importlib
        import app as app_module
        importlib.reload(app_module)
        from fastapi.testclient import TestClient
        client = TestClient(app_module.app)

        resp = client.get("/api/clusters")
        assert resp.status_code == 200
        clusters = resp.json()
        if clusters:
            name = clusters[0]["name"]
            status_resp = client.get(f"/api/clusters/{name}/status")
            data = status_resp.json()
            assert data["reachable"] is False


class TestSeedFileIsolation:
    def test_demo_does_not_mutate_seed_files(self, demo_client, seed_clusters):
        """Operations should write to the temp data dir, not the seed directory."""
        seed_dir = Path(__file__).parent.parent / "seed"
        import json
        original = json.loads((seed_dir / "clusters.json").read_text())

        demo_client.post("/api/clusters", json={
            "name": "mutation-test",
            "display_name": "Mutation Test",
            "kubeconfig_path": "/fake",
            "lat": 0.0,
            "lon": 0.0,
        })

        after = json.loads((seed_dir / "clusters.json").read_text())
        assert len(after) == len(original), "Seed clusters.json was mutated"


class TestFullLifecycle:
    def test_deploy_then_move_then_delete(self, demo_client, seed_clusters):
        """Full model lifecycle: deploy → verify → move → verify → delete → verify."""
        src = seed_clusters[0]["name"]
        tgt = seed_clusters[1]["name"]

        resp = demo_client.post(f"/api/clusters/{src}/models", json={
            "model_name": "lifecycle-model",
            "model_id": "org/lifecycle",
            "namespace": "lifecycle-ns",
            "replicas": 1,
            "gpu_count": 1,
        })
        assert resp.status_code == 200

        models = demo_client.get(f"/api/clusters/{src}/models").json()
        assert any(m["name"] == "lifecycle-model" for m in models)

        resp = demo_client.post(
            f"/api/clusters/{src}/models/lifecycle-ns/lifecycle-model/move",
            json={"target_cluster": tgt},
        )
        assert resp.status_code == 200

        src_models = demo_client.get(f"/api/clusters/{src}/models").json()
        assert not any(m["name"] == "lifecycle-model" for m in src_models)

        tgt_models = demo_client.get(f"/api/clusters/{tgt}/models").json()
        assert any(m["name"] == "lifecycle-model" for m in tgt_models)

        resp = demo_client.delete(f"/api/clusters/{tgt}/models/lifecycle-ns/lifecycle-model")
        assert resp.status_code == 200

        tgt_models = demo_client.get(f"/api/clusters/{tgt}/models").json()
        assert not any(m["name"] == "lifecycle-model" for m in tgt_models)

    def test_spread_with_traffic_after_creation(self, demo_client, seed_clusters):
        """Create a spread and verify traffic appears for it."""
        hub = next(c for c in seed_clusters if "hub" in c.get("tags", []))
        spoke = next(c for c in seed_clusters if c["name"] != hub["name"])

        resp = demo_client.post("/api/spreads", json={
            "model_name": "traffic-test-model",
            "model_namespace": "traffic-ns",
            "model_id": "org/traffic-test",
            "hub": hub["name"],
            "spokes": [spoke["name"]],
        })
        assert resp.status_code == 200
        spread_id = resp.json()["spread"]["id"]

        traffic = demo_client.get("/api/spreads/traffic").json()
        assert spread_id in traffic["spreads"]
        assert spoke["name"] in traffic["spreads"][spread_id]

    def test_metrics_reflect_model_changes(self, demo_client, seed_clusters, seed_models):
        """Deploying a model should increase the active_models count."""
        before = demo_client.get("/api/metrics/summary").json()

        demo_client.post(f"/api/clusters/{seed_clusters[0]['name']}/models", json={
            "model_name": "metrics-model",
            "model_id": "org/metrics",
            "namespace": "metrics-ns",
            "replicas": 1,
            "gpu_count": 1,
        })

        after = demo_client.get("/api/metrics/summary").json()
        assert after["active_models"] == before["active_models"] + 1


class TestScenarioOverrides:
    def test_cluster_status_reflects_overrides(self, demo_client):
        demo_client.post("/api/demo/scenario", json={
            "cluster_overrides": {
                "vai": {"health": "red", "gpu_avg": 99.0},
            },
        })
        status = demo_client.get("/api/clusters/vai/status").json()
        assert status["health"] == "red"
        assert status["gpu_avg"] == 99.0
        assert status["ready_nodes"] < status["node_count"]

    def test_cluster_details_topology_matches_health(self, demo_client):
        demo_client.post("/api/demo/scenario", json={
            "cluster_overrides": {
                "satch": {"health": "yellow"},
            },
        })
        details = demo_client.get("/api/clusters/satch/details").json()
        workers = [n for n in details["topology"] if "worker" in n["roles"]]
        not_ready = [w for w in workers if not w["ready"]]
        assert len(not_ready) == 1

    def test_traffic_multipliers_zero_produces_no_traffic(self, demo_client):
        demo_client.post("/api/demo/scenario", json={
            "traffic_multipliers": {"satch": 0, "bumblefoot": 0},
        })
        traffic = demo_client.get("/api/spreads/traffic").json()
        for spoke_rates in traffic["spreads"].values():
            for spoke, data in spoke_rates.items():
                assert data["req_rate"] == 0

    def test_metrics_summary_tps_zero_with_no_traffic(self, demo_client):
        demo_client.post("/api/demo/scenario", json={
            "traffic_multipliers": {"satch": 0, "bumblefoot": 0},
        })
        summary = demo_client.get("/api/metrics/summary").json()
        assert summary["tokens_per_sec"] == 0.0

    def test_clear_scenario_reverts_to_defaults(self, demo_client):
        demo_client.post("/api/demo/scenario", json={
            "cluster_overrides": {"vai": {"health": "red", "gpu_avg": 99.0}},
        })
        demo_client.delete("/api/demo/scenario")
        status = demo_client.get("/api/clusters/vai/status").json()
        assert status["health"] == "green"
        assert status["gpu_avg"] != 99.0

    def test_scenario_rejects_unknown_fields(self, demo_client):
        resp = demo_client.post("/api/demo/scenario", json={
            "cluster_override": {"vai": {"health": "red"}},
        })
        assert resp.status_code == 200
        status = demo_client.get("/api/clusters/vai/status").json()
        assert status["health"] != "red"


class TestDemoGuideEndpoint:
    def test_returns_javascript(self, demo_client):
        resp = demo_client.get("/demo-guide.js")
        assert resp.status_code == 200
        assert "application/javascript" in resp.headers["content-type"]

    def test_contains_stages(self, demo_client):
        resp = demo_client.get("/demo-guide.js")
        assert "STAGES" in resp.text
        assert "Healthy Fleet" in resp.text


class TestDemoReset:
    def test_reset_restores_seed_state(self, demo_client, seed_clusters, seed_models):
        """After modifications, POST /api/demo/reset restores original seed data."""
        name = seed_clusters[0]["name"]
        demo_client.post(f"/api/clusters/{name}/models", json={
            "model_name": "pre-reset-model",
            "model_id": "org/pre-reset",
            "namespace": "reset-ns",
            "replicas": 1,
            "gpu_count": 1,
        })
        models_before_reset = demo_client.get(f"/api/clusters/{name}/models").json()
        assert any(m["name"] == "pre-reset-model" for m in models_before_reset)

        resp = demo_client.post("/api/demo/reset")
        assert resp.status_code == 200

        models_after_reset = demo_client.get(f"/api/clusters/{name}/models").json()
        assert not any(m["name"] == "pre-reset-model" for m in models_after_reset)
        assert len(models_after_reset) == len(seed_models[name])

    def test_reset_restores_clusters(self, demo_client, seed_clusters):
        demo_client.post("/api/clusters", json={
            "name": "reset-cluster",
            "display_name": "Reset Cluster",
            "kubeconfig_path": "/fake",
            "lat": 0.0,
            "lon": 0.0,
        })
        demo_client.post("/api/demo/reset")
        clusters = demo_client.get("/api/clusters").json()
        names = [c["name"] for c in clusters]
        assert "reset-cluster" not in names
        assert len(clusters) == len(seed_clusters)
