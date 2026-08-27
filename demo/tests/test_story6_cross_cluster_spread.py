"""Story 6: Cross-Cluster Spread

As an operator, I can set up multi-cluster load balancing for a model.
"""


class TestListSpreads:
    def test_returns_seeded_spreads(self, demo_client, seed_spreads):
        resp = demo_client.get("/api/spreads")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == len(seed_spreads)

    def test_each_spread_has_required_fields(self, demo_client):
        resp = demo_client.get("/api/spreads")
        required = {"id", "model_id", "model_name", "model_namespace", "hub", "spokes", "verified"}
        for spread in resp.json():
            missing = required - set(spread.keys())
            assert not missing, f"Spread '{spread.get('id', '?')}' missing: {missing}"

    def test_seeded_spreads_are_verified(self, demo_client, seed_spreads):
        """In demo mode, seeded spreads should report as verified."""
        resp = demo_client.get("/api/spreads")
        for spread in resp.json():
            assert spread["verified"] is True, (
                f"Spread '{spread['id']}' should be verified in demo mode"
            )


class TestCreateSpread:
    def test_create_spread(self, demo_client, seed_clusters):
        hub = next(c for c in seed_clusters if "hub" in c.get("tags", []))
        spoke = next(c for c in seed_clusters if c["name"] != hub["name"])
        resp = demo_client.post("/api/spreads", json={
            "model_name": "new-model",
            "model_namespace": "new-ns",
            "model_id": "org/new-model",
            "hub": hub["name"],
            "spokes": [spoke["name"]],
        })
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        assert "spread" in resp.json()

    def test_created_spread_appears_in_list(self, demo_client, seed_clusters, seed_spreads):
        hub = next(c for c in seed_clusters if "hub" in c.get("tags", []))
        spoke = next(c for c in seed_clusters if c["name"] != hub["name"])
        demo_client.post("/api/spreads", json={
            "model_name": "listed-model",
            "model_namespace": "listed-ns",
            "model_id": "org/listed-model",
            "hub": hub["name"],
            "spokes": [spoke["name"]],
        })
        resp = demo_client.get("/api/spreads")
        model_names = [s["model_name"] for s in resp.json()]
        assert "listed-model" in model_names

    def test_create_with_non_hub_cluster_returns_400(self, demo_client, seed_clusters):
        non_hub = next(c for c in seed_clusters if "hub" not in c.get("tags", []))
        spoke = next(c for c in seed_clusters if c["name"] != non_hub["name"])
        resp = demo_client.post("/api/spreads", json={
            "model_name": "fail-model",
            "model_namespace": "fail-ns",
            "model_id": "org/fail",
            "hub": non_hub["name"],
            "spokes": [spoke["name"]],
        })
        assert resp.status_code == 400

    def test_create_with_nonexistent_hub_returns_404(self, demo_client, seed_clusters):
        spoke = seed_clusters[0]["name"]
        resp = demo_client.post("/api/spreads", json={
            "model_name": "fail-model",
            "model_namespace": "fail-ns",
            "model_id": "org/fail",
            "hub": "nonexistent",
            "spokes": [spoke],
        })
        assert resp.status_code == 404

    def test_create_with_nonexistent_spoke_returns_404(self, demo_client, seed_clusters):
        hub = next(c for c in seed_clusters if "hub" in c.get("tags", []))
        resp = demo_client.post("/api/spreads", json={
            "model_name": "fail-model",
            "model_namespace": "fail-ns",
            "model_id": "org/fail",
            "hub": hub["name"],
            "spokes": ["nonexistent"],
        })
        assert resp.status_code == 404

    def test_create_with_no_spokes_returns_400(self, demo_client, seed_clusters):
        hub = next(c for c in seed_clusters if "hub" in c.get("tags", []))
        resp = demo_client.post("/api/spreads", json={
            "model_name": "fail-model",
            "model_namespace": "fail-ns",
            "model_id": "org/fail",
            "hub": hub["name"],
            "spokes": [],
        })
        assert resp.status_code == 400

    def test_create_duplicate_returns_409(self, demo_client, seed_clusters):
        hub = next(c for c in seed_clusters if "hub" in c.get("tags", []))
        spoke = next(c for c in seed_clusters if c["name"] != hub["name"])
        body = {
            "model_name": "dup-model",
            "model_namespace": "dup-ns",
            "model_id": "org/dup",
            "hub": hub["name"],
            "spokes": [spoke["name"]],
        }
        demo_client.post("/api/spreads", json=body)
        resp = demo_client.post("/api/spreads", json=body)
        assert resp.status_code == 409


class TestDeleteSpread:
    def test_delete_spread(self, demo_client, seed_spreads):
        spread_id = seed_spreads[0]["id"]
        resp = demo_client.delete(f"/api/spreads/{spread_id}")
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_deleted_spread_gone_from_list(self, demo_client, seed_spreads):
        spread_id = seed_spreads[0]["id"]
        demo_client.delete(f"/api/spreads/{spread_id}")
        resp = demo_client.get("/api/spreads")
        ids = [s["id"] for s in resp.json()]
        assert spread_id not in ids

    def test_delete_nonexistent_spread_returns_404(self, demo_client):
        resp = demo_client.delete("/api/spreads/nonexistent")
        assert resp.status_code == 404
