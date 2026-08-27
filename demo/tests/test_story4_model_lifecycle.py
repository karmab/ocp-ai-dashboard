"""Story 4: Model Lifecycle

As an operator, I can move models between clusters and decommission them.
"""


class TestDeleteModel:
    def test_delete_model(self, demo_client, seed_clusters, seed_models):
        cluster = seed_clusters[0]
        models = seed_models[cluster["name"]]
        assert len(models) > 0
        m = models[0]
        resp = demo_client.delete(
            f"/api/clusters/{cluster['name']}/models/{m['namespace']}/{m['name']}"
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_deleted_model_gone_from_list(self, demo_client, seed_clusters, seed_models):
        cluster = seed_clusters[0]
        m = seed_models[cluster["name"]][0]
        demo_client.delete(
            f"/api/clusters/{cluster['name']}/models/{m['namespace']}/{m['name']}"
        )
        resp = demo_client.get(f"/api/clusters/{cluster['name']}/models")
        names = [model["name"] for model in resp.json()]
        assert m["name"] not in names

    def test_delete_nonexistent_model_returns_404(self, demo_client, seed_clusters):
        name = seed_clusters[0]["name"]
        resp = demo_client.delete(f"/api/clusters/{name}/models/fake-ns/fake-model")
        assert resp.status_code == 404

    def test_delete_on_nonexistent_cluster_returns_404(self, demo_client):
        resp = demo_client.delete("/api/clusters/nonexistent/models/ns/model")
        assert resp.status_code == 404


class TestMoveModel:
    def test_move_model_to_target(self, demo_client, seed_clusters, seed_models):
        source = seed_clusters[0]
        target = seed_clusters[1]
        m = seed_models[source["name"]][0]
        resp = demo_client.post(
            f"/api/clusters/{source['name']}/models/{m['namespace']}/{m['name']}/move",
            json={"target_cluster": target["name"]},
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_move_removes_from_source(self, demo_client, seed_clusters, seed_models):
        source = seed_clusters[0]
        target = seed_clusters[2]
        m = seed_models[source["name"]][0]
        demo_client.post(
            f"/api/clusters/{source['name']}/models/{m['namespace']}/{m['name']}/move",
            json={"target_cluster": target["name"]},
        )
        resp = demo_client.get(f"/api/clusters/{source['name']}/models")
        names = [model["name"] for model in resp.json()]
        assert m["name"] not in names

    def test_move_adds_to_target(self, demo_client, seed_clusters, seed_models):
        source = seed_clusters[0]
        target = seed_clusters[2]
        m = seed_models[source["name"]][0]
        demo_client.post(
            f"/api/clusters/{source['name']}/models/{m['namespace']}/{m['name']}/move",
            json={"target_cluster": target["name"]},
        )
        resp = demo_client.get(f"/api/clusters/{target['name']}/models")
        names = [model["name"] for model in resp.json()]
        assert m["name"] in names

    def test_move_preserves_model_fields(self, demo_client, seed_clusters, seed_models):
        source = seed_clusters[0]
        target = seed_clusters[2]
        m = seed_models[source["name"]][0]
        demo_client.post(
            f"/api/clusters/{source['name']}/models/{m['namespace']}/{m['name']}/move",
            json={"target_cluster": target["name"]},
        )
        resp = demo_client.get(f"/api/clusters/{target['name']}/models")
        moved = next(model for model in resp.json() if model["name"] == m["name"])
        assert moved["model_id"] == m["model_id"]
        assert moved["namespace"] == m["namespace"]

    def test_move_to_nonexistent_target_returns_404(self, demo_client, seed_clusters, seed_models):
        source = seed_clusters[0]
        m = seed_models[source["name"]][0]
        resp = demo_client.post(
            f"/api/clusters/{source['name']}/models/{m['namespace']}/{m['name']}/move",
            json={"target_cluster": "nonexistent"},
        )
        assert resp.status_code == 404

    def test_move_nonexistent_model_returns_404(self, demo_client, seed_clusters):
        resp = demo_client.post(
            f"/api/clusters/{seed_clusters[0]['name']}/models/fake-ns/fake-model/move",
            json={"target_cluster": seed_clusters[1]["name"]},
        )
        assert resp.status_code == 404
