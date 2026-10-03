"""Story 5: App Deployment

As an operator, I can deploy and manage containerized apps alongside models.
"""


class TestListApps:
    def test_returns_seeded_apps(self, demo_client, seed_clusters, seed_apps):
        name = seed_clusters[0]["name"]
        resp = demo_client.get(f"/api/clusters/{name}/apps")
        assert resp.status_code == 200
        data = resp.json()
        expected = seed_apps.get(name, [])
        assert len(data) == len(expected)

    def test_each_app_has_required_fields(self, demo_client, seed_clusters, seed_apps):
        for cluster in seed_clusters:
            if not seed_apps.get(cluster["name"]):
                continue
            resp = demo_client.get(f"/api/clusters/{cluster['name']}/apps")
            required = {"name", "namespace", "image", "replicas", "ready_replicas", "ready", "route_url"}
            for app in resp.json():
                missing = required - set(app.keys())
                assert not missing, f"App '{app.get('name', '?')}' missing: {missing}"

    def test_seeded_app_has_route_url(self, demo_client, seed_clusters, seed_apps):
        for cluster in seed_clusters:
            apps = seed_apps.get(cluster["name"], [])
            for expected_app in apps:
                if expected_app["route_url"]:
                    resp = demo_client.get(f"/api/clusters/{cluster['name']}/apps")
                    app = next(a for a in resp.json() if a["name"] == expected_app["name"])
                    assert app["route_url"] is not None
                    assert app["route_url"].startswith("https://")

    def test_unknown_cluster_returns_404(self, demo_client):
        resp = demo_client.get("/api/clusters/nonexistent/apps")
        assert resp.status_code == 404


class TestDeployApp:
    def test_deploy_app(self, demo_client, seed_clusters):
        name = seed_clusters[0]["name"]
        resp = demo_client.post(f"/api/clusters/{name}/apps", json={
            "app_name": "test-app",
            "image": "quay.io/test/app:latest",
            "namespace": "test-apps",
            "replicas": 1,
        })
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_deployed_app_has_route_url(self, demo_client, seed_clusters):
        name = seed_clusters[0]["name"]
        resp = demo_client.post(f"/api/clusters/{name}/apps", json={
            "app_name": "route-test",
            "image": "quay.io/test/app:latest",
            "namespace": "test-apps",
            "replicas": 1,
        })
        assert resp.json().get("route_url") is not None
        assert resp.json()["route_url"].startswith("https://")

    def test_deployed_app_route_contains_app_name(self, demo_client, seed_clusters):
        name = seed_clusters[0]["name"]
        resp = demo_client.post(f"/api/clusters/{name}/apps", json={
            "app_name": "myapp",
            "image": "quay.io/test/app:latest",
            "namespace": "my-ns",
            "replicas": 1,
        })
        assert "myapp" in resp.json()["route_url"]

    def test_deployed_app_appears_in_list(self, demo_client, seed_clusters):
        name = seed_clusters[0]["name"]
        demo_client.post(f"/api/clusters/{name}/apps", json={
            "app_name": "listed-app",
            "image": "quay.io/test/app:latest",
            "namespace": "test-apps",
            "replicas": 1,
        })
        resp = demo_client.get(f"/api/clusters/{name}/apps")
        app_names = [a["name"] for a in resp.json()]
        assert "listed-app" in app_names

    def test_deployed_app_preserves_fields(self, demo_client, seed_clusters):
        name = seed_clusters[0]["name"]
        demo_client.post(f"/api/clusters/{name}/apps", json={
            "app_name": "field-app",
            "image": "quay.io/org/specific:v2",
            "namespace": "specific-ns",
            "replicas": 3,
        })
        resp = demo_client.get(f"/api/clusters/{name}/apps")
        app = next(a for a in resp.json() if a["name"] == "field-app")
        assert app["image"] == "quay.io/org/specific:v2"
        assert app["namespace"] == "specific-ns"
        assert app["replicas"] == 3

    def test_deploy_to_nonexistent_cluster_returns_404(self, demo_client):
        resp = demo_client.post("/api/clusters/nonexistent/apps", json={
            "app_name": "test",
            "image": "test:latest",
            "namespace": "test",
            "replicas": 1,
        })
        assert resp.status_code == 404


class TestDeleteApp:
    def test_delete_app(self, demo_client, seed_clusters, seed_apps):
        cluster = seed_clusters[0]
        apps = seed_apps.get(cluster["name"], [])
        assert len(apps) > 0, "Need seeded apps for delete test"
        app = apps[0]
        resp = demo_client.delete(
            f"/api/clusters/{cluster['name']}/apps/{app['namespace']}/{app['name']}"
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_deleted_app_gone_from_list(self, demo_client, seed_clusters, seed_apps):
        cluster = seed_clusters[0]
        app = seed_apps[cluster["name"]][0]
        demo_client.delete(
            f"/api/clusters/{cluster['name']}/apps/{app['namespace']}/{app['name']}"
        )
        resp = demo_client.get(f"/api/clusters/{cluster['name']}/apps")
        names = [a["name"] for a in resp.json()]
        assert app["name"] not in names
