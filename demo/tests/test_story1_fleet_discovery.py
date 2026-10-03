"""Story 1: Fleet Discovery

As an operator, I can see my clusters on a map with real-time health.
"""
import re


class TestClusterList:
    def test_returns_all_seeded_clusters(self, demo_client, seed_clusters):
        resp = demo_client.get("/api/clusters")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == len(seed_clusters)

    def test_each_cluster_has_display_fields(self, demo_client):
        resp = demo_client.get("/api/clusters")
        for cluster in resp.json():
            assert "name" in cluster
            assert "display_name" in cluster
            assert "lat" in cluster
            assert "lon" in cluster
            assert "tags" in cluster


class TestClusterStatus:
    def test_returns_reachable(self, demo_client, seed_clusters):
        name = seed_clusters[0]["name"]
        resp = demo_client.get(f"/api/clusters/{name}/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["reachable"] is True

    def test_returns_node_list(self, demo_client, seed_clusters):
        name = seed_clusters[0]["name"]
        resp = demo_client.get(f"/api/clusters/{name}/status")
        data = resp.json()
        assert isinstance(data["nodes"], list)
        assert len(data["nodes"]) > 0

    def test_node_count_matches_list(self, demo_client, seed_clusters):
        name = seed_clusters[0]["name"]
        resp = demo_client.get(f"/api/clusters/{name}/status")
        data = resp.json()
        assert data["node_count"] == len(data["nodes"])

    def test_ready_nodes_lte_total(self, demo_client, seed_clusters):
        name = seed_clusters[0]["name"]
        resp = demo_client.get(f"/api/clusters/{name}/status")
        data = resp.json()
        assert data["ready_nodes"] <= data["node_count"]
        assert data["ready_nodes"] > 0

    def test_returns_region(self, demo_client, seed_clusters):
        name = seed_clusters[0]["name"]
        resp = demo_client.get(f"/api/clusters/{name}/status")
        data = resp.json()
        assert isinstance(data["region"], str)
        assert len(data["region"]) > 0

    def test_does_not_override_seeded_coordinates(self, demo_client, seed_clusters):
        """Detected coordinates should match seeded values, not drift."""
        for cluster in seed_clusters:
            resp = demo_client.get(f"/api/clusters/{cluster['name']}/status")
            data = resp.json()
            if "detected_lat" in data:
                assert abs(data["detected_lat"] - cluster["lat"]) < 0.01
                assert abs(data["detected_lon"] - cluster["lon"]) < 0.01


class TestClusterHealth:
    def test_returns_health_field(self, demo_client, seed_clusters):
        name = seed_clusters[0]["name"]
        resp = demo_client.get(f"/api/clusters/{name}/status")
        data = resp.json()
        assert data["health"] in ("green", "yellow", "red")

    def test_returns_health_details(self, demo_client, seed_clusters):
        name = seed_clusters[0]["name"]
        resp = demo_client.get(f"/api/clusters/{name}/status")
        data = resp.json()
        assert isinstance(data["health_details"], str)
        assert len(data["health_details"]) > 0

    def test_not_all_clusters_same_health(self, demo_client, seed_clusters):
        """At least one cluster should differ in health for visual variety."""
        healths = set()
        for cluster in seed_clusters:
            resp = demo_client.get(f"/api/clusters/{cluster['name']}/status")
            healths.add(resp.json()["health"])
        assert len(healths) >= 2, "All clusters have identical health — no visual variety"

    def test_returns_gpu_fields(self, demo_client, seed_clusters):
        name = seed_clusters[0]["name"]
        resp = demo_client.get(f"/api/clusters/{name}/status")
        data = resp.json()
        assert "gpu_avg" in data
        assert "gpu_count" in data
        assert isinstance(data["gpu_avg"], (int, float))
        assert isinstance(data["gpu_count"], int)
        assert data["gpu_count"] > 0


class TestClusterDetails:
    def test_returns_ocp_version(self, demo_client, seed_clusters):
        name = seed_clusters[0]["name"]
        resp = demo_client.get(f"/api/clusters/{name}/details")
        assert resp.status_code == 200
        data = resp.json()
        assert re.match(r"4\.\d+\.\d+", data["ocp_version"])

    def test_returns_platform(self, demo_client, seed_clusters):
        name = seed_clusters[0]["name"]
        resp = demo_client.get(f"/api/clusters/{name}/details")
        data = resp.json()
        assert data["platform"] in ("AWS", "Azure", "libvirt", "GCP", "BareMetal", "None")

    def test_returns_topology(self, demo_client, seed_clusters):
        name = seed_clusters[0]["name"]
        resp = demo_client.get(f"/api/clusters/{name}/details")
        data = resp.json()
        assert isinstance(data["topology"], list)
        assert len(data["topology"]) > 0

    def test_topology_nodes_have_required_fields(self, demo_client, seed_clusters):
        name = seed_clusters[0]["name"]
        resp = demo_client.get(f"/api/clusters/{name}/details")
        required = {"name", "roles", "ready", "cpu", "memory", "gpu", "instance_type", "zone", "arch"}
        for node in resp.json()["topology"]:
            missing = required - set(node.keys())
            assert not missing, f"Node '{node.get('name', '?')}' missing: {missing}"

    def test_at_least_one_node_has_gpu(self, demo_client, seed_clusters):
        """At least one cluster should have GPU nodes for demo purposes."""
        found_gpu = False
        for cluster in seed_clusters:
            resp = demo_client.get(f"/api/clusters/{cluster['name']}/details")
            if resp.status_code != 200:
                continue
            for node in resp.json()["topology"]:
                if int(node["gpu"]) > 0:
                    found_gpu = True
                    break
            if found_gpu:
                break
        assert found_gpu, "No GPU nodes found across any cluster"

    def test_returns_rhoai_components(self, demo_client, seed_clusters):
        name = seed_clusters[0]["name"]
        resp = demo_client.get(f"/api/clusters/{name}/details")
        data = resp.json()
        assert isinstance(data["rhoai_components"], dict)
        assert len(data["rhoai_components"]) > 0

    def test_rhoai_components_have_version_and_phase(self, demo_client, seed_clusters):
        name = seed_clusters[0]["name"]
        resp = demo_client.get(f"/api/clusters/{name}/details")
        for comp_name, info in resp.json()["rhoai_components"].items():
            assert "version" in info, f"Component '{comp_name}' missing version"
            assert "phase" in info, f"Component '{comp_name}' missing phase"

    def test_at_least_one_rhoai_component_succeeded(self, demo_client, seed_clusters):
        name = seed_clusters[0]["name"]
        resp = demo_client.get(f"/api/clusters/{name}/details")
        phases = [info["phase"] for info in resp.json()["rhoai_components"].values()]
        assert "Succeeded" in phases

    def test_unknown_cluster_returns_404(self, demo_client):
        resp = demo_client.get("/api/clusters/nonexistent/details")
        assert resp.status_code == 404

    def test_unknown_cluster_status_returns_404(self, demo_client):
        resp = demo_client.get("/api/clusters/nonexistent/status")
        assert resp.status_code == 404
