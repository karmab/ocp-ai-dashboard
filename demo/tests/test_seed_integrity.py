"""Tests that seed data files are internally consistent and cross-referenced."""


class TestSeedClusters:
    def test_seed_has_at_least_three_clusters(self, seed_clusters):
        assert len(seed_clusters) >= 3

    def test_each_cluster_has_required_fields(self, seed_clusters):
        required = {"name", "display_name", "kubeconfig", "lat", "lon", "tags"}
        for cluster in seed_clusters:
            missing = required - set(cluster.keys())
            assert not missing, f"Cluster '{cluster.get('name', '?')}' missing: {missing}"

    def test_cluster_names_are_unique(self, seed_clusters):
        names = [c["name"] for c in seed_clusters]
        assert len(names) == len(set(names)), f"Duplicate cluster names: {names}"

    def test_at_least_one_cluster_tagged_hub(self, seed_clusters):
        hubs = [c for c in seed_clusters if "hub" in c.get("tags", [])]
        assert len(hubs) >= 1, "No cluster tagged as 'hub'"

    def test_coordinates_are_valid(self, seed_clusters):
        for c in seed_clusters:
            assert -90 <= c["lat"] <= 90, f"'{c['name']}' lat out of range: {c['lat']}"
            assert -180 <= c["lon"] <= 180, f"'{c['name']}' lon out of range: {c['lon']}"


class TestSeedSpreads:
    def test_seed_has_at_least_one_spread(self, seed_spreads):
        assert len(seed_spreads) >= 1

    def test_each_spread_has_required_fields(self, seed_spreads):
        required = {"id", "model_id", "model_name", "model_namespace", "hub", "spokes", "created_at"}
        for spread in seed_spreads:
            missing = required - set(spread.keys())
            assert not missing, f"Spread '{spread.get('id', '?')}' missing: {missing}"

    def test_spread_ids_are_unique(self, seed_spreads):
        ids = [s["id"] for s in seed_spreads]
        assert len(ids) == len(set(ids))

    def test_spread_has_at_least_one_spoke(self, seed_spreads):
        for spread in seed_spreads:
            assert len(spread["spokes"]) >= 1, f"Spread '{spread['id']}' has no spokes"

    def test_spread_hub_references_valid_cluster(self, seed_spreads, seed_clusters):
        cluster_names = {c["name"] for c in seed_clusters}
        for spread in seed_spreads:
            assert spread["hub"] in cluster_names, (
                f"Spread '{spread['id']}' hub '{spread['hub']}' not in clusters"
            )

    def test_spread_spokes_reference_valid_clusters(self, seed_spreads, seed_clusters):
        cluster_names = {c["name"] for c in seed_clusters}
        for spread in seed_spreads:
            for spoke in spread["spokes"]:
                assert spoke in cluster_names, (
                    f"Spread '{spread['id']}' spoke '{spoke}' not in clusters"
                )

    def test_spread_hub_is_tagged_hub(self, seed_spreads, seed_clusters):
        cluster_map = {c["name"]: c for c in seed_clusters}
        for spread in seed_spreads:
            hub_cluster = cluster_map[spread["hub"]]
            assert "hub" in hub_cluster.get("tags", []), (
                f"Spread '{spread['id']}' hub '{spread['hub']}' not tagged as 'hub'"
            )

    def test_spread_spokes_do_not_include_hub(self, seed_spreads):
        for spread in seed_spreads:
            assert spread["hub"] not in spread["spokes"], (
                f"Spread '{spread['id']}' has hub '{spread['hub']}' listed as a spoke"
            )


class TestSeedModels:
    def test_model_clusters_reference_valid_clusters(self, seed_models, seed_clusters):
        cluster_names = {c["name"] for c in seed_clusters}
        for cluster_name in seed_models:
            assert cluster_name in cluster_names, (
                f"Model store references unknown cluster '{cluster_name}'"
            )

    def test_each_model_has_required_fields(self, seed_models):
        required = {"name", "namespace", "model_id", "replicas", "gpu_per_replica", "ready", "status"}
        for cluster_name, models in seed_models.items():
            for model in models:
                missing = required - set(model.keys())
                assert not missing, (
                    f"Model '{model.get('name', '?')}' on '{cluster_name}' missing: {missing}"
                )

    def test_at_least_one_model_is_ready(self, seed_models):
        all_models = [m for models in seed_models.values() for m in models]
        ready = [m for m in all_models if m["ready"]]
        assert len(ready) >= 1

    def test_at_least_one_model_is_progressing(self, seed_models):
        all_models = [m for models in seed_models.values() for m in models]
        progressing = [m for m in all_models if m["status"] == "Progressing"]
        assert len(progressing) >= 1, "Seed should include at least one Progressing model for demo variety"

    def test_model_replicas_are_positive(self, seed_models):
        for cluster_name, models in seed_models.items():
            for model in models:
                assert model["replicas"] >= 1, (
                    f"Model '{model['name']}' on '{cluster_name}' has invalid replicas"
                )


class TestSeedApps:
    def test_app_clusters_reference_valid_clusters(self, seed_apps, seed_clusters):
        cluster_names = {c["name"] for c in seed_clusters}
        for cluster_name in seed_apps:
            assert cluster_name in cluster_names, (
                f"App store references unknown cluster '{cluster_name}'"
            )

    def test_each_app_has_required_fields(self, seed_apps):
        required = {"name", "namespace", "image", "replicas", "ready_replicas", "ready", "route_url"}
        for cluster_name, apps in seed_apps.items():
            for app in apps:
                missing = required - set(app.keys())
                assert not missing, (
                    f"App '{app.get('name', '?')}' on '{cluster_name}' missing: {missing}"
                )

    def test_at_least_one_cluster_has_an_app(self, seed_apps):
        total = sum(len(apps) for apps in seed_apps.values())
        assert total >= 1

    def test_app_route_urls_are_https(self, seed_apps):
        for cluster_name, apps in seed_apps.items():
            for app in apps:
                if app["route_url"]:
                    assert app["route_url"].startswith("https://"), (
                        f"App '{app['name']}' route_url should be https"
                    )
