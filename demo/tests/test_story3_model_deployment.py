"""Story 3: Model Deployment

As an operator, I can deploy AI models to clusters from a catalog.
"""


class TestListModels:
    def test_returns_seeded_models(self, demo_client, seed_clusters, seed_models):
        name = seed_clusters[0]["name"]
        resp = demo_client.get(f"/api/clusters/{name}/models")
        assert resp.status_code == 200
        data = resp.json()
        expected = seed_models.get(name, [])
        assert len(data) == len(expected)

    def test_each_model_has_required_fields(self, demo_client, seed_clusters):
        name = seed_clusters[0]["name"]
        resp = demo_client.get(f"/api/clusters/{name}/models")
        required = {"name", "namespace", "model_id", "replicas", "gpu_per_replica", "ready", "status"}
        for model in resp.json():
            missing = required - set(model.keys())
            assert not missing, f"Model '{model.get('name', '?')}' missing: {missing}"

    def test_includes_ready_and_progressing_models(self, demo_client, seed_clusters, seed_models):
        """Across all clusters, there should be both Ready and Progressing models."""
        statuses = set()
        for cluster in seed_clusters:
            resp = demo_client.get(f"/api/clusters/{cluster['name']}/models")
            for model in resp.json():
                statuses.add(model["status"])
        assert "Ready" in statuses
        assert "Progressing" in statuses

    def test_unknown_cluster_returns_404(self, demo_client):
        resp = demo_client.get("/api/clusters/nonexistent/models")
        assert resp.status_code == 404


class TestDeployModel:
    def test_deploy_model(self, demo_client, seed_clusters):
        name = seed_clusters[0]["name"]
        resp = demo_client.post(f"/api/clusters/{name}/models", json={
            "model_name": "test-deploy",
            "model_id": "Qwen/Qwen3-14B",
            "namespace": "test-ns",
            "replicas": 2,
            "gpu_count": 2,
        })
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_deployed_model_appears_in_list(self, demo_client, seed_clusters):
        name = seed_clusters[0]["name"]
        demo_client.post(f"/api/clusters/{name}/models", json={
            "model_name": "appears-test",
            "model_id": "test/model",
            "namespace": "test-ns",
            "replicas": 1,
            "gpu_count": 1,
        })
        resp = demo_client.get(f"/api/clusters/{name}/models")
        model_names = [m["name"] for m in resp.json()]
        assert "appears-test" in model_names

    def test_deployed_model_preserves_fields(self, demo_client, seed_clusters):
        name = seed_clusters[0]["name"]
        demo_client.post(f"/api/clusters/{name}/models", json={
            "model_name": "field-check",
            "model_id": "org/specific-model",
            "namespace": "my-ns",
            "replicas": 3,
            "gpu_count": 4,
        })
        resp = demo_client.get(f"/api/clusters/{name}/models")
        model = next(m for m in resp.json() if m["name"] == "field-check")
        assert model["model_id"] == "org/specific-model"
        assert model["namespace"] == "my-ns"
        assert model["replicas"] == 3
        assert model["gpu_per_replica"] == 4

    def test_deploy_cpu_only(self, demo_client, seed_clusters):
        name = seed_clusters[0]["name"]
        resp = demo_client.post(f"/api/clusters/{name}/models", json={
            "model_name": "cpu-model",
            "model_id": "small/model",
            "namespace": "cpu-ns",
            "replicas": 1,
            "gpu_count": 0,
            "cpu_only": True,
        })
        assert resp.status_code == 200
        models = demo_client.get(f"/api/clusters/{name}/models").json()
        model = next(m for m in models if m["name"] == "cpu-model")
        assert model["gpu_per_replica"] == 0

    def test_deploy_to_nonexistent_cluster_returns_404(self, demo_client):
        resp = demo_client.post("/api/clusters/nonexistent/models", json={
            "model_name": "test",
            "model_id": "test/model",
            "namespace": "test",
            "replicas": 1,
            "gpu_count": 1,
        })
        assert resp.status_code == 404
