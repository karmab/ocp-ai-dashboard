"""Story 2: Cluster Management

As an operator, I can register, tag, and remove clusters from the grid.
"""


class TestAddCluster:
    def test_add_cluster_skips_kubeconfig_validation(self, demo_client):
        """In demo mode, kubeconfig path does not need to exist on disk."""
        resp = demo_client.post("/api/clusters", json={
            "name": "new-cluster",
            "display_name": "New Cluster (GCP)",
            "kubeconfig_path": "/nonexistent/path/kubeconfig",
            "lat": 33.45,
            "lon": -112.07,
        })
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_add_cluster_skips_connectivity_test(self, demo_client):
        """In demo mode, no actual k8s connection attempt is made."""
        resp = demo_client.post("/api/clusters", json={
            "name": "offline-cluster",
            "display_name": "Offline Cluster",
            "kubeconfig_path": "/fake/path",
            "lat": 51.51,
            "lon": -0.13,
        })
        assert resp.status_code == 200

    def test_added_cluster_appears_in_list(self, demo_client):
        demo_client.post("/api/clusters", json={
            "name": "added-cluster",
            "display_name": "Added Cluster",
            "kubeconfig_path": "/fake/path",
            "lat": 48.86,
            "lon": 2.35,
        })
        resp = demo_client.get("/api/clusters")
        names = [c["name"] for c in resp.json()]
        assert "added-cluster" in names

    def test_duplicate_name_returns_400(self, demo_client, seed_clusters):
        existing = seed_clusters[0]
        resp = demo_client.post("/api/clusters", json={
            "name": existing["name"],
            "display_name": "Duplicate",
            "kubeconfig_path": "/fake/path",
            "lat": 0.0,
            "lon": 0.0,
        })
        assert resp.status_code == 400

    def test_added_cluster_has_demo_status(self, demo_client):
        """A newly added cluster should be reachable in demo mode."""
        demo_client.post("/api/clusters", json={
            "name": "status-check",
            "display_name": "Status Check",
            "kubeconfig_path": "/fake/path",
            "lat": 35.68,
            "lon": 139.69,
        })
        resp = demo_client.get("/api/clusters/status-check/status")
        assert resp.status_code == 200
        assert resp.json()["reachable"] is True


class TestTags:
    def test_add_tag(self, demo_client, seed_clusters):
        name = seed_clusters[1]["name"]
        resp = demo_client.put(f"/api/clusters/{name}/tags", json={
            "tags": seed_clusters[1].get("tags", []) + ["new-tag"],
        })
        assert resp.status_code == 200
        assert "new-tag" in resp.json()["tags"]

    def test_remove_tag(self, demo_client, seed_clusters):
        cluster = seed_clusters[0]
        original_tags = cluster.get("tags", [])
        assert len(original_tags) > 0, "Need a cluster with tags for this test"
        new_tags = [t for t in original_tags if t != original_tags[0]]
        resp = demo_client.put(f"/api/clusters/{cluster['name']}/tags", json={
            "tags": new_tags,
        })
        assert resp.status_code == 200
        assert original_tags[0] not in resp.json()["tags"]

    def test_tags_persist_across_reads(self, demo_client, seed_clusters):
        name = seed_clusters[1]["name"]
        demo_client.put(f"/api/clusters/{name}/tags", json={"tags": ["persisted"]})
        resp = demo_client.get("/api/clusters")
        cluster = next(c for c in resp.json() if c["name"] == name)
        assert "persisted" in cluster["tags"]

    def test_tag_nonexistent_cluster_returns_404(self, demo_client):
        resp = demo_client.put("/api/clusters/nonexistent/tags", json={"tags": ["x"]})
        assert resp.status_code == 404


class TestRemoveCluster:
    def test_remove_cluster(self, demo_client, seed_clusters):
        name = seed_clusters[2]["name"]
        resp = demo_client.delete(f"/api/clusters/{name}")
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_removed_cluster_gone_from_list(self, demo_client, seed_clusters):
        name = seed_clusters[2]["name"]
        demo_client.delete(f"/api/clusters/{name}")
        resp = demo_client.get("/api/clusters")
        names = [c["name"] for c in resp.json()]
        assert name not in names
